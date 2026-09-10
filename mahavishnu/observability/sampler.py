"""Fixed-cadence metric sampler for change-point detection (Tier 1 Phase 6).

# Implements: REQ-009

The :class:`MetricSampler` produces a (ts, value) time series
from :class:`~mahavishnu.core.observability.ObservabilityManager`'s
performance metrics at a configurable cadence. The default cadence
is 60 seconds (matches ``mahavishnu/pools/fitness_analyzer.py``'s
precedent). The sampler is the input feed for both
``_evaluate_change_point`` (CUSUM / Page-Hinkley) and
``_evaluate_3sigma`` (sliding-window z-score) in Phase 6.

Design choices:

* The sampler is *passive* — it does not spawn a background
  thread or asyncio task. The caller (Phase 6 wiring in
  ``ObservabilityManager._evaluate_change_point``) calls
  :meth:`observe` after each tick. This keeps the sampler
  deterministic and testable without ``asyncio`` lifecycle
  coupling.
* The per-metric ring buffer has bounded length
  (``max_samples``) — the detector window is implicit in the
  buffer length, not a separate time-windowed store. For the
  60-second cadence the spec's "1 hour of samples" needs
  ``max_samples >= 60``; we default to 7200 (2 hours) to match
  the ``fitness_analyzer`` TTL convention.
* The sampler is metric-name-agnostic — a single instance can
  feed any number of metric series, keyed by name.

Req: REQ-009
"""  # Implements: REQ-009

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import time
from typing import Any


DEFAULT_CADENCE_SECONDS = 60.0
DEFAULT_MAX_SAMPLES = 7_200  # 2 hours at 60s cadence; matches fitness_analyzer TTL=7200s


@dataclass(frozen=True, slots=True)
class MetricSample:
    """A single (ts, value) sample for one metric.

    Attributes:
        metric: the metric name (e.g. ``"pool_queue_depth"``).
        ts_monotonic: monotonic timestamp in seconds (from
            ``time.monotonic()``).
        ts_wall: wall-clock UTC datetime for log/span emission.
        value: the sampled metric value.
    """

    metric: str
    ts_monotonic: float
    ts_wall: datetime
    value: float


class MetricSampler:
    """Fixed-cadence sampler producing a per-metric time series.

    The sampler is *passive*: callers invoke :meth:`observe` once
    per tick to feed a value. The sampler's job is to:

    1. Buffer the (metric, value) pair with a timestamp.
    2. Trim the buffer to ``max_samples`` (ring buffer per metric).
    3. Expose a per-metric series for the change-point detector
       and the 3-sigma reference detector.

    Args:
        cadence_seconds: target tick interval. Default 60s (matches
            ``fitness_analyzer``). Used for OTel span attribute
            reporting; the sampler does not enforce a tick rate
            itself.
        max_samples: ring-buffer length per metric. Default 7200
            (2 hours at 60s cadence).
        source: optional callable that returns the current
            ``ObservabilityManager.get_performance_metrics()``
            snapshot. When None, callers pass values directly to
            :meth:`observe`.
    """

    def __init__(
        self,
        cadence_seconds: float = DEFAULT_CADENCE_SECONDS,
        max_samples: int = DEFAULT_MAX_SAMPLES,
        source: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if cadence_seconds <= 0.0:
            raise ValueError(f"cadence_seconds must be > 0, got {cadence_seconds!r}")
        if max_samples < 1:
            raise ValueError(f"max_samples must be >= 1, got {max_samples!r}")
        self.cadence_seconds: float = cadence_seconds
        self.max_samples: int = max_samples
        self._source: Callable[[], dict[str, Any]] | None = source
        self._buffers: dict[str, deque[MetricSample]] = defaultdict(
            lambda: deque(maxlen=self.max_samples)
        )

    def observe(self, metric: str, value: float) -> MetricSample:
        """Record one observation for ``metric`` and return the sample.

        Args:
            metric: metric name (e.g. ``"pool_queue_depth"``).
            value: the sampled value. NaN/Inf are dropped silently
                (the detector will treat the missing sample as
                ``None`` rather than choke on a bad value).

        Returns:
            The recorded :class:`MetricSample`. If ``value`` is
            non-finite, the buffer is unchanged and the
            returned sample carries the dropped value (callers
            can detect the drop with ``math.isfinite(sample.value)``).
        """
        import math

        ts_mono = time.monotonic()
        ts_wall = datetime.now(UTC)
        sample = MetricSample(
            metric=metric,
            ts_monotonic=ts_mono,
            ts_wall=ts_wall,
            value=value,
        )
        if math.isfinite(value):
            self._buffers[metric].append(sample)
        return sample

    def tick(self) -> dict[str, float]:
        """Pull the current snapshot from ``source`` and observe each metric.

        When ``source`` is None, this method returns an empty dict
        (callers should drive :meth:`observe` directly).

        Returns:
            A ``{metric_name: observed_value}`` dict for the
            current tick. Callers can use this to forward the
            observed value to the change-point detector.
        """
        if self._source is None:
            return {}
        snapshot = self._source()
        # The ObservabilityManager.get_performance_metrics() return
        # shape is a dict; we treat each scalar entry as one
        # metric. Sub-dicts (workflow_performance) are walked one
        # level deep so the detector can monitor per-workflow
        # stats if needed.
        observed: dict[str, float] = {}
        for key, value in snapshot.items():
            if isinstance(value, (int, float)):
                self.observe(key, float(value))
                observed[key] = float(value)
            elif isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, (int, float)):
                        composed = f"{key}.{sub_key}"
                        self.observe(composed, float(sub_value))
                        observed[composed] = float(sub_value)
        return observed

    def series(self, metric: str) -> list[MetricSample]:
        """Return a snapshot of the buffered samples for ``metric``."""
        return list(self._buffers.get(metric, ()))

    def values(self, metric: str) -> list[float]:
        """Return the buffered values for ``metric`` (oldest first)."""
        return [s.value for s in self._buffers.get(metric, ())]

    def clear(self, metric: str | None = None) -> None:
        """Clear the buffer for one metric (or all metrics)."""
        if metric is None:
            self._buffers.clear()
        else:
            self._buffers.pop(metric, None)


__all__ = [
    "DEFAULT_CADENCE_SECONDS",
    "DEFAULT_MAX_SAMPLES",
    "MetricSample",
    "MetricSampler",
]
