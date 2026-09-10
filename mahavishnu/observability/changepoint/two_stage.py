"""Two-stage warn/confirm change-point detector (REQ-005 extension).

The :class:`TwoStageDetector` composes a low-threshold warn detector
with a high-threshold confirm detector to resolve the §1 latency vs
§7 FP-rate trade-off documented in
``docs/audits/2026-09-10-changepoint-validation.md``. The §1 latency
gate is checked on the warn detector; the §7 FP gate is checked on
the confirmed-alert stream (a warning that is not corroborated by
the confirm detector within the correlation window is discarded).

State machine:

    idle  --[warn fires]-->  warning_pending
    warning_pending  --[confirm fires within window]-->  confirmed
    warning_pending  --[window expires without confirm]-->  idle
    warning_pending  --[warn fires again (LATEST captured)]-->  warning_pending
    confirmed  --[next update() after alert emission]-->  idle

If ``warn_detector`` fires again while in ``warning_pending``, the
latest warning result captures in ``_last_warning_result`` and the
warn detector resets; the next confirm carries the LATEST warning
score, not the first. (See ``update()`` lines for the in-loop
``if warn_fired:`` branch under ``warning_pending``.)

Mathematical reference: see ``docs/plans/2026-09-10-bodai-math-initiatives-tier1.md``
§1 (success metrics) and the calibration sweep table in
``docs/audits/2026-09-10-changepoint-validation.md`` for the empirical
ARL₀ / latency numbers at the production defaults.

Req: REQ-005 (extension — composes existing CUSUMDetector + PageHinkleyDetector).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mahavishnu.observability.changepoint.cusum import ChangePointDetector, ChangePointResult
from mahavishnu.observability.changepoint.severity import classify_severity

TwoStageState = Literal["idle", "warning_pending", "confirmed"]

DEFAULT_CONFIRM_WINDOW = 100


@dataclass(frozen=True, slots=True)
class TwoStageResult:
    """Result of a single ``update()`` call on a TwoStageDetector.

    Attributes:
        state: current state-machine position.
        warning_result: the underlying warn detector's ChangePointResult
            (None if state == "idle"; populated when the warn detector fired).
        confirm_result: the underlying confirm detector's ChangePointResult
            (None if state != "confirmed").
        samples_since_warning: samples elapsed since the most recent warn
            fire. 0 in the ``idle`` state; positive in ``warning_pending``;
            reset to 0 after a confirmed alert is emitted.
        severity: classified severity of the confirmed alert. None
            unless state == "confirmed". Mirrors the existing
            ``ObservabilityManager._classify_drift_severity`` contract.
        detector_warn: class name of the warn detector (lowercased).
        detector_confirm: class name of the confirm detector (lowercased).
    """

    state: TwoStageState
    warning_result: ChangePointResult | None
    confirm_result: ChangePointResult | None
    samples_since_warning: int
    severity: Literal["minor", "moderate", "critical"] | None
    detector_warn: str
    detector_confirm: str


class TwoStageDetector:
    """Two-stage warn/confirm change-point detector.

    Args:
        warn_detector: low-threshold detector that produces "warning"
            events quickly on small shifts (typically CUSUMDetector with
            slack=0.25, threshold=8.0; median 0.5σ latency ~28 samples,
            ~30 FP / 10,080 samples on stationary noise).
        confirm_detector: high-threshold detector that produces
            "confirmation" events rarely (typically CUSUMDetector with
            slack=0.25, threshold=14.0 or PageHinkleyDetector with
            threshold=10.0; median 0.5σ latency ~50 samples, ~1.64
            FP / 10,080 samples).
        confirm_window_samples: confirm must fire within N samples
            AFTER the warn (inclusive of the Nth sample). On the Nth
            sample, the confirm check runs before the window-expiry
            check, so a confirm at exactly the boundary still emits
            the alert. If the confirm detector doesn't fire within
            this window, the state machine returns to ``idle`` and the
            warning is discarded (treated as a transient).

    Req: REQ-005 (extension)
    """

    __slots__ = (
        "_confirm_window_samples",
        "_last_warning_result",
        "_samples_since_warning",
        "_state",
        "confirm_detector",
        "warn_detector",
    )

    def __init__(
        self,
        warn_detector: ChangePointDetector,
        confirm_detector: ChangePointDetector,
        confirm_window_samples: int = DEFAULT_CONFIRM_WINDOW,
    ) -> None:
        if confirm_window_samples <= 0:
            raise ValueError(
                f"confirm_window_samples must be > 0, got {confirm_window_samples}"
            )
        self.warn_detector: ChangePointDetector = warn_detector
        self.confirm_detector: ChangePointDetector = confirm_detector
        self._confirm_window_samples: int = confirm_window_samples
        self._state: TwoStageState = "idle"
        self._samples_since_warning: int = 0
        self._last_warning_result: ChangePointResult | None = None

    @property
    def state(self) -> TwoStageState:
        return self._state

    @property
    def samples_since_warning(self) -> int:
        return self._samples_since_warning

    def update(self, observation: float) -> TwoStageResult:
        """Feed one observation; advance the state machine.

        The same observation is fed to BOTH detectors (they see the
        same stream). The state machine evolves based on whether each
        detector fires:

        - ``idle`` + warn fires → ``warning_pending`` (warn is reset)
        - ``warning_pending`` + confirm fires → ``confirmed`` (both reset on next call)
        - ``warning_pending`` + window expires → ``idle`` (warn is reset)
        - ``confirmed`` → emit the prior ``TwoStageResult`` with state
          "confirmed", then advance to ``idle`` on this call
        """
        warn_result = self.warn_detector.update(observation)
        confirm_result = self.confirm_detector.update(observation)

        warn_fired = warn_result.detected
        confirm_fired = confirm_result.detected

        severity: Literal["minor", "moderate", "critical"] | None = None

        if self._state == "confirmed":
            # The previous update produced a confirmed alert; emit it
            # via the prior TwoStageResult and reset to idle now.
            self._state = "idle"
            self._samples_since_warning = 0
            self._last_warning_result = None
            self.warn_detector.reset()
            self.confirm_detector.reset()
            # Re-run the same observation through the freshly-reset
            # detectors so the state machine evolves correctly for
            # THIS observation.
            warn_result = self.warn_detector.update(observation)
            confirm_result = self.confirm_detector.update(observation)
            warn_fired = warn_result.detected
            confirm_fired = confirm_result.detected

        if self._state == "idle":
            if warn_fired:
                self._state = "warning_pending"
                self._samples_since_warning = 0
                self._last_warning_result = warn_result
                # Reset warn so the next observation starts fresh; the
                # warn detector would otherwise stay above threshold.
                self.warn_detector.reset()
                return TwoStageResult(
                    state="warning_pending",
                    warning_result=warn_result,
                    confirm_result=None,
                    samples_since_warning=0,
                    severity=None,
                    detector_warn=type(self.warn_detector).__name__.lower(),
                    detector_confirm=type(self.confirm_detector).__name__.lower(),
                )
            # No state change
            return TwoStageResult(
                state="idle",
                warning_result=None,
                confirm_result=None,
                samples_since_warning=0,
                severity=None,
                detector_warn=type(self.warn_detector).__name__.lower(),
                detector_confirm=type(self.confirm_detector).__name__.lower(),
            )

        # state == "warning_pending"
        self._samples_since_warning += 1
        if warn_fired:
            # Capture the latest warning result so the integration
            # layer can read both warning and confirm scores from the
            # confirmed alert (the warn detector is reset so it can
            # fire again cleanly).
            self._last_warning_result = warn_result
            self.warn_detector.reset()
        if confirm_fired:
            severity = classify_severity(
                confirm_result.score, confirm_result.threshold
            )
            self._state = "confirmed"
            # The integration layer reads the "confirmed" result and
            # emits the alert; on the NEXT update() we'll see state ==
            # "confirmed" at the top and reset to idle. So leave
            # both detectors dirty for this observation (the alert
            # carry the score/threshold of the fire that triggered it).
            return TwoStageResult(
                state="confirmed",
                warning_result=self._last_warning_result,
                confirm_result=confirm_result,
                samples_since_warning=self._samples_since_warning,
                severity=severity,
                detector_warn=type(self.warn_detector).__name__.lower(),
                detector_confirm=type(self.confirm_detector).__name__.lower(),
            )

        if self._samples_since_warning >= self._confirm_window_samples:
            # Ordering invariant: the confirm-fire check above runs BEFORE
            # this window-expiry check on every observation, so a confirm
            # at exactly the Nth sample (the boundary) still emits the
            # alert rather than being silently discarded.
            # Window expired without confirm — discard the warning.
            self._state = "idle"
            self._samples_since_warning = 0
            self._last_warning_result = None
            self.warn_detector.reset()
            self.confirm_detector.reset()
            # Re-run the same observation through the freshly-reset
            # detectors so subsequent state evolution is correct.
            warn_result = self.warn_detector.update(observation)
            confirm_result = self.confirm_detector.update(observation)
            warn_fired = warn_result.detected
            confirm_fired = confirm_result.detected
            # Recurse into the idle handling above: keep this method's
            # return type simple by re-running the same logic.
            if warn_fired:
                self._state = "warning_pending"
                self._samples_since_warning = 0
                self._last_warning_result = warn_result
                self.warn_detector.reset()
                return TwoStageResult(
                    state="warning_pending",
                    warning_result=warn_result,
                    confirm_result=None,
                    samples_since_warning=0,
                    severity=None,
                    detector_warn=type(self.warn_detector).__name__.lower(),
                    detector_confirm=type(self.confirm_detector).__name__.lower(),
                )
            return TwoStageResult(
                state="idle",
                warning_result=None,
                confirm_result=None,
                samples_since_warning=0,
                severity=None,
                detector_warn=type(self.warn_detector).__name__.lower(),
                detector_confirm=type(self.confirm_detector).__name__.lower(),
            )

        # Still warning_pending, confirm hasn't fired yet
        return TwoStageResult(
            state="warning_pending",
            warning_result=None,
            confirm_result=None,
            samples_since_warning=self._samples_since_warning,
            severity=None,
            detector_warn=type(self.warn_detector).__name__.lower(),
            detector_confirm=type(self.confirm_detector).__name__.lower(),
        )

    def reset(self) -> None:
        """Reset both detectors and the state machine."""
        self.warn_detector.reset()
        self.confirm_detector.reset()
        self._state = "idle"
        self._samples_since_warning = 0
        self._last_warning_result = None


__all__ = ["TwoStageDetector", "TwoStageResult", "TwoStageState"]