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

    def test_last_arrival_monotonic_updates_on_append(self) -> None:
        """S2: last_arrival_monotonic is updated on every successful append."""
        buf = QueueingObservationBuffer(pool_id="test")
        assert buf.last_arrival_monotonic == 0.0
        buf.append(inter_arrival=0.5, service=0.1)
        first = buf.last_arrival_monotonic
        assert first > 0.0
        time.sleep(0.02)
        buf.append(inter_arrival=0.5, service=0.1)
        second = buf.last_arrival_monotonic
        assert second > first
        # The delta between last_arrival_monotonic values is the
        # actual wall-clock between calls (~20ms sleep + overhead).
        assert (second - first) >= 0.02

    def test_last_arrival_monotonic_unchanged_on_invalid_append(self) -> None:
        """Invalid (NaN/Inf/zero/negative) appends do NOT update last_arrival_monotonic."""
        buf = QueueingObservationBuffer(pool_id="test")
        buf.append(inter_arrival=0.5, service=0.1)
        first = buf.last_arrival_monotonic
        time.sleep(0.01)
        buf.append(inter_arrival=float("nan"), service=0.1)
        buf.append(inter_arrival=1.0, service=float("inf"))
        buf.append(inter_arrival=0.0, service=0.5)
        # last_arrival_monotonic did not advance on the dropped inputs
        assert buf.last_arrival_monotonic == first

    def test_seconds_since_last_arrival(self) -> None:
        buf = QueueingObservationBuffer(pool_id="test")
        # Cold buffer: returns 0.0 sentinel (no arrival yet).
        assert buf.seconds_since_last_arrival() == 0.0
        buf.append(inter_arrival=0.5, service=0.1)
        time.sleep(0.05)
        elapsed = buf.seconds_since_last_arrival()
        assert elapsed >= 0.05
        # Bounded above: time.sleep + Python overhead is well under 1s.
        assert elapsed < 1.0

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
    def test_default_is_enabled_after_phase_4(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig()
        # Phase 4 flipped queueing_enabled to True; per-environment
        # opt-out is via settings/local.yaml or env var
        # MAHAVISHNU_POOLS__QUEUEING_ENABLED=false.
        assert cfg.queueing_enabled is True

    def test_can_be_disabled(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig(queueing_enabled=False)
        assert cfg.queueing_enabled is False

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


# ---------------------------------------------------------------------------
# C1: PoolManager._apply_queueing_penalty wiring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyQueueingPenalty:
    """C1: the queueing penalty must actually influence pool selection.

    Before C1, _apply_queueing_penalty (or its inline equivalent in
    route_task) computed predicted_wait_s for the inner-selected pool
    and used it only as a label suffix on the routing-decision record.
    The selected pool was always the inner selector's pick. C1 fixes
    this: for multi-candidate selectors (LEAST_LOADED, ROUND_ROBIN,
    RANDOM) the candidate with the lowest predicted wait wins once
    at least one pool has a fitted model.
    """

    def _build_manager(self):  # type: ignore[no-untyped-def]
        """Minimal PoolManager construction with two pools."""
        from mahavishnu.pools.manager import PoolManager, PoolSelector

        # Real constructor (no __new__) so internal dicts are set.
        try:
            return PoolManager(message_bus=None)
        except Exception:
            # The test environment may not have a configured
            # MahavishnuSettings; the apply_queueing_penalty tests
            # only touch _queueing_buffers and _pools, which are
            # both set in __init__.
            from unittest.mock import MagicMock

            mgr = PoolManager.__new__(PoolManager)
            mgr._pools = {}
            mgr._queueing_buffers = {}
            return mgr

    def test_no_predictions_returns_inner_pick(self) -> None:
        """Without predictions, the inner pick is unchanged."""
        from mahavishnu.pools.manager import PoolSelector

        mgr = self._build_manager()
        mgr._pools["pool_a"] = object()
        mgr._pools["pool_b"] = object()

        chosen, wait, effective, affected = mgr._apply_queueing_penalty(
            "pool_a", PoolSelector.LEAST_LOADED
        )
        assert chosen == "pool_a"
        assert wait is None
        assert effective == "least_loaded"
        assert affected is False

    def test_lowest_wait_wins_for_multi_candidate_selectors(self) -> None:
        """pool_b has lower predicted wait — should be chosen over pool_a."""
        from mahavishnu.pools.manager import PoolSelector
        from mahavishnu.pools.queueing import MmcQueue

        mgr = self._build_manager()
        mgr._pools["pool_a"] = object()
        mgr._pools["pool_b"] = object()

        buf_a = QueueingObservationBuffer(
            pool_id="pool_a", min_observations=2, min_seconds=0.0
        )
        # Fit pool_a with high arrival rate (more load)
        buf_a.arrivals = deque([0.1] * 10)  # arrival_rate = 10/s
        buf_a.services = deque([0.1] * 10)  # service_rate = 10/s
        m = MmcQueue.fit_from_observations(
            list(buf_a.arrivals), list(buf_a.services), num_workers=1
        )
        assert m is not None
        buf_a.fitted_model = m
        buf_a.last_arrival_monotonic = 1.0  # suppress refit trigger
        mgr._queueing_buffers["pool_a"] = buf_a

        buf_b = QueueingObservationBuffer(
            pool_id="pool_b", min_observations=2, min_seconds=0.0
        )
        buf_b.arrivals = deque([10.0] * 10)  # arrival_rate = 0.1/s (idle)
        buf_b.services = deque([0.1] * 10)  # service_rate = 10/s
        m2 = MmcQueue.fit_from_observations(
            list(buf_b.arrivals), list(buf_b.services), num_workers=1
        )
        assert m2 is not None
        buf_b.fitted_model = m2
        buf_b.last_arrival_monotonic = 1.0
        mgr._queueing_buffers["pool_b"] = buf_b

        # Inner selector picked pool_a (high load). Queueing re-ranks
        # to pool_b (idle).
        chosen, wait, effective, affected = mgr._apply_queueing_penalty(
            "pool_a", PoolSelector.LEAST_LOADED
        )
        assert chosen == "pool_b"
        assert wait is not None and wait >= 0.0
        assert effective == "least_loaded+queueing"
        assert affected is True

    def test_affinity_selector_does_not_swap(self) -> None:
        """AFFINITY is a single-candidate selector — no swap, only advise."""
        from mahavishnu.pools.manager import PoolSelector
        from mahavishnu.pools.queueing import MmcQueue

        mgr = self._build_manager()
        mgr._pools["pool_a"] = object()
        mgr._pools["pool_b"] = object()

        # Even with pool_b being idle, AFFINITY should still pick
        # pool_a (the affinity target). Use rho=0.5 so the model
        # returns a finite predicted wait (safe_expected_wait_time
        # treats rho >= 0.95 as inf).
        buf_a = QueueingObservationBuffer(pool_id="pool_a", min_observations=2, min_seconds=0.0)
        buf_a.arrivals = deque([2.0] * 10)  # arrival_rate=0.5/s
        buf_a.services = deque([1.0] * 10)  # service_rate=1/s -> rho=0.5
        buf_a.fitted_model = MmcQueue.fit_from_observations(
            list(buf_a.arrivals), list(buf_a.services), num_workers=1
        )
        buf_a.last_arrival_monotonic = 1.0
        mgr._queueing_buffers["pool_a"] = buf_a

        chosen, wait, effective, affected = mgr._apply_queueing_penalty(
            "pool_a", PoolSelector.AFFINITY
        )
        assert chosen == "pool_a"
        assert affected is False
        assert effective == "affinity"
        # The predicted wait is still reported for the audit trail.
        assert wait is not None

    def test_inner_pick_already_lowest_no_swap(self) -> None:
        """If the inner pick has the lowest wait, no swap occurs."""
        from mahavishnu.pools.manager import PoolSelector
        from mahavishnu.pools.queueing import MmcQueue

        mgr = self._build_manager()
        mgr._pools["pool_a"] = object()
        mgr._pools["pool_b"] = object()

        # pool_a is idle; pool_b is overloaded. Inner picked pool_a.
        buf_a = QueueingObservationBuffer(pool_id="pool_a", min_observations=2, min_seconds=0.0)
        buf_a.arrivals = deque([10.0] * 10)
        buf_a.services = deque([0.1] * 10)
        buf_a.fitted_model = MmcQueue.fit_from_observations(
            list(buf_a.arrivals), list(buf_a.services), num_workers=1
        )
        buf_a.last_arrival_monotonic = 1.0
        mgr._queueing_buffers["pool_a"] = buf_a

        buf_b = QueueingObservationBuffer(pool_id="pool_b", min_observations=2, min_seconds=0.0)
        buf_b.arrivals = deque([0.1] * 10)
        buf_b.services = deque([0.1] * 10)
        buf_b.fitted_model = MmcQueue.fit_from_observations(
            list(buf_b.arrivals), list(buf_b.services), num_workers=1
        )
        buf_b.last_arrival_monotonic = 1.0
        mgr._queueing_buffers["pool_b"] = buf_b

        chosen, _, effective, affected = mgr._apply_queueing_penalty(
            "pool_a", PoolSelector.LEAST_LOADED
        )
        assert chosen == "pool_a"
        assert affected is False
        assert effective == "least_loaded"

    def test_safe_predicted_wait_filters_inf_and_negative(self) -> None:
        """_compute_predicted_wait returns None for inf/negative results."""
        from unittest.mock import MagicMock

        mgr = self._build_manager()

        # Model whose safe_expected_wait_time returns inf
        class _InfModel:
            def safe_expected_wait_time(self, *args, **kwargs):
                return float("inf")

        buf = MagicMock()
        buf.fitted_model = _InfModel()
        assert mgr._compute_predicted_wait(buf) is None

        # Model that raises — boundary handler swallows
        class _BoomModel:
            def safe_expected_wait_time(self, *args, **kwargs):
                raise RuntimeError("model corrupt")

        buf2 = MagicMock()
        buf2.fitted_model = _BoomModel()
        assert mgr._compute_predicted_wait(buf2) is None

        # No fitted model
        buf3 = MagicMock()
        buf3.fitted_model = None
        assert mgr._compute_predicted_wait(buf3) is None
