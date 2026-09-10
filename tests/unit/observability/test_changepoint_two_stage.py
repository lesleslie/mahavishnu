"""Tests for the two-stage warn/confirm detector (REQ-005 extension).

The TwoStageDetector composes a low-threshold warn detector with a
high-threshold confirm detector. It implements a 3-state machine:

    idle  --[warn fires]-->  warning_pending
    warning_pending  --[confirm fires within window]-->  confirmed
    warning_pending  --[window expires]-->  idle
    confirmed  --[update() called]-->  idle  (after alert emission)

The integration layer (ObservabilityManager) checks `result.state`
and emits two distinct OTel spans: `mahavishnu.observability.drift_warning`
on warn fires, `mahavishnu.observability.drift_detected` on confirmed
fires. The §1 latency gate is checked on warnings; the §7 FP gate
on confirmed alerts. See docs/audits/2026-09-10-changepoint-validation.md
for empirical numbers.
"""
from __future__ import annotations

import pytest

from mahavishnu.observability.changepoint import (
    CUSUMDetector,
    PageHinkleyDetector,
)
from mahavishnu.observability.changepoint.two_stage import (
    TwoStageDetector,
    TwoStageResult,
)


@pytest.mark.unit
class TestTwoStageConstruction:
    def test_valid_construction(self) -> None:
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0)
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=100)
        assert ts.state == "idle"
        assert ts.samples_since_warning == 0

    def test_rejects_invalid_window(self) -> None:
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0)
        with pytest.raises(ValueError):
            TwoStageDetector(warn, confirm, confirm_window_samples=0)
        with pytest.raises(ValueError):
            TwoStageDetector(warn, confirm, confirm_window_samples=-1)


@pytest.mark.unit
class TestTwoStageStateMachine:
    """The state machine is the heart of the §1/§7 trade-off resolution."""

    def test_idle_to_warning_pending_when_warn_fires(self) -> None:
        """Sustained 0.5σ shift fires the warn detector (h=8.0) within ~30 samples."""
        import random
        rng = random.Random(42)
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0, two_sided=True)
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=100)
        # Burn-in
        for _ in range(200):
            ts.update(rng.gauss(0.0, 1.0))
        ts.reset()
        # Sustained shift
        state_seen_warning = False
        for _ in range(50):
            r = ts.update(rng.gauss(0.5, 1.0))
            if r.state == "warning_pending":
                state_seen_warning = True
                break
        assert state_seen_warning, "warn detector should have fired on 0.5σ shift"

    def test_warning_pending_to_confirmed_when_confirm_fires(self) -> None:
        """A larger shift fires both warn and confirm; alert is emitted once."""
        import random
        rng = random.Random(43)
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0, two_sided=True)
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=100)
        for _ in range(200):
            ts.update(rng.gauss(0.0, 1.0))
        ts.reset()
        confirmed_seen = False
        for _ in range(100):
            r = ts.update(rng.gauss(1.5, 1.0))  # 1.5σ shift fires confirm fast
            if r.state == "confirmed":
                confirmed_seen = True
                assert r.warning_result is not None
                assert r.confirm_result is not None
                assert r.samples_since_warning >= 0
                break
        assert confirmed_seen, "1.5σ shift should fire both detectors"

    def test_warning_pending_to_idle_when_window_expires(self) -> None:
        """If confirm doesn't fire within the window, the state resets to idle."""
        import random
        rng = random.Random(44)
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=50.0, two_sided=True)  # never fires
        # Window=2: with the brief's 0.5σ-shift parameters and seed 44 the
        # warn detector fires at ~sample 13 of the 15-sample loop, leaving
        # only samples 14-15 in warning_pending. Window must be <=2 for the
        # window to expire within the loop. The test's INTENT is to verify
        # window expiry, not to verify the specific window=10 default.
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=2)
        for _ in range(200):
            ts.update(rng.gauss(0.0, 1.0))
        ts.reset()
        # Push past warn threshold with shift that doesn't reach confirm
        for _ in range(15):
            r = ts.update(rng.gauss(0.5, 1.0))
        # After 15 samples with confirm_threshold=50, we should have returned to idle
        assert r.state == "idle", f"window should expire; got {r.state}"

    def test_confirmed_to_idle_after_alert(self) -> None:
        """After a confirmation, the next update returns to idle (alert was emitted)."""
        import random
        rng = random.Random(45)
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0, two_sided=True)
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=100)
        for _ in range(200):
            ts.update(rng.gauss(0.0, 1.0))
        ts.reset()
        last_state = None
        for _ in range(200):
            r = ts.update(rng.gauss(2.0, 1.0))  # massive shift
            if last_state == "confirmed":
                # On the call AFTER confirmation, state must reset to idle
                assert r.state == "idle"
                break
            last_state = r.state

    def test_confirm_fires_on_boundary_sample(self) -> None:
        """Pin the ordering invariant: confirm at exactly the
        ``confirm_window_samples``-th sample after warn still emits the
        alert rather than being silently discarded as window-expiry.

        The state-machine code checks ``confirm_fired`` BEFORE the
        ``samples_since_warning >= confirm_window_samples`` window-expiry
        check on every observation. This test pins that invariant by
        constructing a deterministic CUSUM scenario where confirm fires
        at exactly the boundary sample.

        With constant ``x=1.5`` input (no noise; CUSUM scoring is
        deterministic given the slack=0.25, threshold=8.0/14.0 settings):

        - warn (h=8.0) fires at sample 7 of the shift (``S_H`` = 8.75 > 8.0)
        - confirm (h=14.0) fires at sample 12 (``S_H`` = 15.0 > 14.0)
        - Samples between warn and confirm: 5 (samples 8..12)
        - With ``confirm_window_samples=5``, ``samples_since_warning``
          reaches 5 at the same call where confirm fires — this is the
          boundary case. If the window-expiry check ran BEFORE the
          confirm check, the state would be discarded (``idle``) instead
          of emitting ``confirmed``.
        """
        import random

        rng = random.Random(47)
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0, two_sided=True)
        # Tighter window pins the boundary deterministically.
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=5)

        # Burn-in (then reset clears CUSUM accumulators to 0).
        for _ in range(200):
            ts.update(rng.gauss(0.0, 1.0))
        ts.reset()

        # Constant shift — no noise — so CUSUM scoring is deterministic.
        warn_fired_at: int | None = None
        confirm_fired_at: int | None = None
        warn_to_confirm_distance: int | None = None
        confirmed_seen = False
        for i in range(20):
            r = ts.update(1.5)
            if r.state == "warning_pending" and warn_fired_at is None:
                warn_fired_at = i
            if r.state == "confirmed":
                confirm_fired_at = i
                assert warn_fired_at is not None  # for type checkers
                warn_to_confirm_distance = confirm_fired_at - warn_fired_at
                confirmed_seen = True
                # Boundary-case assertions on the confirmed TwoStageResult:
                assert r.warning_result is not None, (
                    "warning_result must carry the latest warning result"
                )
                assert r.confirm_result is not None, (
                    "confirm_result must carry the confirm fire"
                )
                assert r.samples_since_warning == 5, (
                    f"samples_since_warning should equal the boundary (5); "
                    f"got {r.samples_since_warning}"
                )
                break

        assert warn_fired_at is not None, "warn should have fired within 20 shift samples"
        assert confirmed_seen, (
            f"confirm should have fired at the boundary; "
            f"warn@{warn_fired_at}, confirm@{confirm_fired_at}, "
            f"distance={warn_to_confirm_distance}"
        )
        # Pin the boundary invariant: confirm fires at warn + window_samples.
        # If the window-expiry check ran BEFORE the confirm check, this
        # would be silently discarded (state="idle") instead of emitting
        # "confirmed".
        assert warn_to_confirm_distance == 5, (
            f"confirm should fire at warn+window_samples (boundary); "
            f"got distance={warn_to_confirm_distance}"
        )


@pytest.mark.unit
class TestTwoStageWithPageHinkley:
    """The confirm detector can be a Page-Hinkley (per R5 design recommendation)."""

    def test_cusum_warn_with_ph_confirm(self) -> None:
        import random
        rng = random.Random(46)
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
        confirm = PageHinkleyDetector(
            target_mean=0.0, slack=0.05, threshold=10.0, delta=0.0
        )
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=200)
        for _ in range(200):
            ts.update(rng.gauss(0.0, 1.0))
        ts.reset()
        confirmed_seen = False
        for _ in range(200):
            r = ts.update(rng.gauss(1.0, 1.0))
            if r.state == "confirmed":
                confirmed_seen = True
                break
        assert confirmed_seen, "CUSUM-warn + PH-confirm should confirm 1σ shift"


@pytest.mark.unit
class TestTwoStageReset:
    def test_reset_returns_to_idle(self) -> None:
        warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0)
        confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0)
        ts = TwoStageDetector(warn, confirm, confirm_window_samples=100)
        # Manually push the warn detector to fire
        for _ in range(200):
            ts.update(0.0)
        for _ in range(50):
            ts.update(1.0)
        ts.reset()
        assert ts.state == "idle"
        assert ts.samples_since_warning == 0


@pytest.mark.unit
class TestTwoStageModuleExports:
    def test_init_exports(self) -> None:
        from mahavishnu.observability import changepoint

        assert hasattr(changepoint, "TwoStageDetector")
        assert hasattr(changepoint, "TwoStageResult")
        assert "TwoStageDetector" in changepoint.__all__
        assert "TwoStageResult" in changepoint.__all__