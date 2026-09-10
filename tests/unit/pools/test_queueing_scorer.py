"""Tests for Phase 2 QueueingScorer + PoolManager queueing integration (REQ-002, REQ-003, REQ-008)."""
from __future__ import annotations

import time
from collections import deque

import pytest

from mahavishnu.pools.base import PoolConfig, PoolMetrics
from mahavishnu.pools.queueing import MmcQueue
from mahavishnu.pools.queueing.scorer import (
    DEFAULT_WARMUP_MIN_OBSERVATIONS,
    DEFAULT_WARMUP_MIN_SECONDS,
    QueueingObservationBuffer,
    QueueingScorer,
)
from mahavishnu.core.status import PoolStatus


# ---------------------------------------------------------------------------
# QueueingObservationBuffer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueueingObservationBuffer:
    def test_new_buffer_is_warmup(self) -> None:
        buf = QueueingObservationBuffer(pool_id="test")
        assert buf.ready_to_fit() is False
        assert buf.fitted_model is None

    def test_ready_to_fit_requires_min_observations(self) -> None:
        buf = QueueingObservationBuffer(pool_id="test", min_observations=5)
        for _ in range(4):
            buf.append(inter_arrival=1.0, service=0.5)
        assert buf.ready_to_fit() is False
        for _ in range(1):
            buf.append(inter_arrival=1.0, service=0.5)
        assert buf.ready_to_fit() is True

    def test_due_for_refit_initial_state(self) -> None:
        buf = QueueingObservationBuffer(pool_id="test")
        assert buf.due_for_refit() is True

    def test_due_for_refit_after_fit(self) -> None:
        buf = QueueingObservationBuffer(
            pool_id="test", min_observations=2, min_seconds=0.1
        )
        buf.append(1.0, 0.5)
        buf.append(1.0, 0.5)
        m = buf.fit(num_workers=2)
        assert m is not None
        assert buf.due_for_refit() is False
        time.sleep(0.15)
        assert buf.due_for_refit() is True

    def test_fit_returns_model_with_min_observations(self) -> None:
        buf = QueueingObservationBuffer(pool_id="test", min_observations=2)
        buf.append(inter_arrival=1.0, service=0.5)
        buf.append(inter_arrival=1.0, service=0.5)
        m = buf.fit(num_workers=2)
        assert m is not None
        assert m.arrival_rate == pytest.approx(1.0, rel=1e-9)
        assert m.service_rate == pytest.approx(2.0, rel=1e-9)

    def test_fit_returns_none_when_below_min_observations(self) -> None:
        buf = QueueingObservationBuffer(pool_id="test", min_observations=10)
        buf.append(1.0, 0.5)
        assert buf.fit(num_workers=2) is None

    def test_append_drops_nan_inf(self) -> None:
        buf = QueueingObservationBuffer(pool_id="test")
        import math
        buf.append(inter_arrival=float("nan"), service=0.5)
        buf.append(inter_arrival=1.0, service=float("inf"))
        buf.append(inter_arrival=-1.0, service=0.5)
        buf.append(inter_arrival=0.0, service=0.5)
        assert len(buf.arrivals) == 0
        assert len(buf.services) == 0

    def test_append_drops_zero_arrival(self) -> None:
        """Zero inter-arrival time is meaningless (simultaneous arrivals)."""
        buf = QueueingObservationBuffer(pool_id="test")
        buf.append(inter_arrival=0.0, service=0.5)
        assert len(buf.arrivals) == 0

    def test_fit_failure_keeps_buffer(self) -> None:
        """A failed fit (e.g. length mismatch from upstream bug) does not crash the buffer."""
        buf = QueueingObservationBuffer(pool_id="test", min_observations=2)
        # Append valid pairs then corrupt one:
        buf.arrivals = deque([1.0, 1.0])
        buf.services = deque([0.5])  # length mismatch
        # The fit() will raise (it's not a graceful path) — but
        # the buffer state should still be recoverable.
        try:
            buf.fit(num_workers=2)
        except Exception:  # noqa: BLE001
            pass
        # buffer is still usable
        assert len(buf.arrivals) == 2


# ---------------------------------------------------------------------------
# QueueingScorer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueueingScorer:
    def test_warmup_returns_zero_delta(self) -> None:
        """When no model is set and no buffer is passed, scorer returns 0.0 delta."""
        s = QueueingScorer(inner=None)  # type: ignore[arg-type]
        # Build a minimal pool/tuple so the call works
        # QueueingScorer.score returns the *delta* to apply
        pool = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=2,
            total_workers=2,
        )
        delta = s.score(pool, None)  # type: ignore[arg-type]
        assert delta == 0.0

    def test_with_fitted_model_returns_penalty(self) -> None:
        """When a fitted model is provided, the delta is -weight * predicted_wait."""
        m = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        s = QueueingScorer(inner=None, model=m, penalty_weight=0.1)  # type: ignore[arg-type]
        pool = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=2,
            total_workers=2,
        )
        delta = s.score(pool, None)  # type: ignore[arg-type]
        # delta = -0.1 * W_q
        # W_q at rho=0.25 is (0.25/0.75)/1 = 0.333
        assert delta < 0.0
        assert delta == pytest.approx(-0.1 * (0.25 / 0.75), rel=1e-6)

    def test_unstable_rho_returns_strong_negative(self) -> None:
        """rho >= 1 should return a strongly negative score (do-not-route)."""
        m = MmcQueue(arrival_rate=5.0, service_rate=1.0, num_workers=1)
        s = QueueingScorer(inner=None, model=m)  # type: ignore[arg-type]
        pool = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=1,
            total_workers=1,
        )
        delta = s.score(pool, None)  # type: ignore[arg-type]
        assert delta == -1e9

    def test_with_buffer_fitted_model(self) -> None:
        """When a buffer is provided with a fitted model, scorer uses it."""
        buf = QueueingObservationBuffer(pool_id="x", min_observations=2)
        buf.append(1.0, 0.5)
        buf.append(1.0, 0.5)
        m = buf.fit(num_workers=2)
        assert m is not None
        s = QueueingScorer(inner=None)  # type: ignore[arg-type]
        pool = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=2,
            total_workers=2,
        )
        delta = s.score(pool, None, buffer=buf)  # type: ignore[arg-type]
        assert delta < 0.0

    def test_penalty_weight_scales_delta(self) -> None:
        m = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        pool = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=2,
            total_workers=2,
        )
        d1 = QueueingScorer(inner=None, model=m, penalty_weight=0.1).score(pool, None)  # type: ignore[arg-type]
        d2 = QueueingScorer(inner=None, model=m, penalty_weight=0.5).score(pool, None)  # type: ignore[arg-type]
        # Larger weight → more negative delta
        assert d2 < d1


# ---------------------------------------------------------------------------
# PoolMetrics wait_time_estimate field
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPoolMetricsWaitTimeEstimate:
    def test_default_is_none(self) -> None:
        m = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=2,
            total_workers=2,
        )
        assert m.wait_time_estimate is None
        assert m.queueing_model is None

    def test_can_hold_fitted_model(self) -> None:
        m = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=2,
            total_workers=2,
            wait_time_estimate=0.333,
        )
        assert m.wait_time_estimate == pytest.approx(0.333, rel=1e-9)

    def test_can_hold_mmc_queue_reference(self) -> None:
        model = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        m = PoolMetrics(
            pool_id="x",
            status=PoolStatus.RUNNING,
            active_workers=2,
            total_workers=2,
            queueing_model=model,
        )
        assert m.queueing_model is model


# ---------------------------------------------------------------------------
# Pydantic PoolConfig (core/config.py) queueing_enabled field
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPydanticPoolConfigQueueing:
    def test_default_is_disabled(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig()
        assert cfg.queueing_enabled is False

    def test_can_be_enabled(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig(queueing_enabled=True)
        assert cfg.queueing_enabled is True

    def test_extra_forbid_still_enforced(self) -> None:
        from pydantic import ValidationError

        from mahavishnu.core.config import PoolConfig

        with pytest.raises(ValidationError):
            PoolConfig(unknown_field=True)  # type: ignore[call-arg]

    def test_warmup_min_observations_default(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig()
        assert cfg.queueing_warmup_min_observations == 100

    def test_warmup_min_seconds_default(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig()
        assert cfg.queueing_warmup_min_seconds == 600.0

    def test_warmup_overrides(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig(
            queueing_warmup_min_observations=50,
            queueing_warmup_min_seconds=300.0,
        )
        assert cfg.queueing_warmup_min_observations == 50
        assert cfg.queueing_warmup_min_seconds == 300.0


# ---------------------------------------------------------------------------
# Module public API
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModuleExports:
    def test_init_exports_scorer(self) -> None:
        from mahavishnu.pools import queueing

        assert hasattr(queueing, "QueueingScorer")
        assert hasattr(queueing, "QueueingObservationBuffer")
        assert "QueueingScorer" in queueing.__all__
        assert "QueueingObservationBuffer" in queueing.__all__
        assert "MmcQueue" in queueing.__all__


# ---------------------------------------------------------------------------
# _ALLOWED_LABEL_KEYS — verify new labels accepted
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllowedLabelKeys:
    def test_predicted_wait_bucket_in_allowlist(self) -> None:
        from mahavishnu.observability.metrics import _ALLOWED_LABEL_KEYS

        assert "predicted_wait_bucket" in _ALLOWED_LABEL_KEYS

    def test_effective_selector_in_allowlist(self) -> None:
        from mahavishnu.observability.metrics import _ALLOWED_LABEL_KEYS

        assert "effective_selector" in _ALLOWED_LABEL_KEYS
