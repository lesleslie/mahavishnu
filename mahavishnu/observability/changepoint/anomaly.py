"""3-sigma reference detector for the change-point integration (Phase 6).

# Implements: REQ-006

The :class:`AnomalyResult` dataclass carries the result of the
3-sigma reference detector that runs in parallel with the
CUSUM / Page-Hinkley detector in :class:`ObservabilityManager`
(Phase 6). The 3-sigma detector is a sliding-window z-score
pointwise flag, not a sequential change-point test — it answers
the question "is this single observation > 3σ from the recent
window mean?" while the change-point detector answers
"has the process mean drifted?".

The two are complementary: the 3-sigma detector catches
single-observation spikes; the change-point detector catches
slow drifts. The integration layer runs both in parallel when
``changepoint.reference_detector == "three_sigma"`` (default).

Req: REQ-006 (marker location chosen to satisfy
``audit_requirements.py`` frontmatter scan — the marker must
live in code or tests, not in plan body blocks).
"""  # req: REQ-006

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    """Result of a 3-sigma reference detector evaluation.

    Attributes:
        detected: True iff ``|z| >= 3`` (the 3-sigma threshold).
        z_score: the z-score of the current value relative to the
            sliding window mean and standard deviation.
        current_value: the observation fed to the detector.
        window_mean: the mean of the sliding window used for the
            z-score computation.
        window_std: the standard deviation of the sliding window.
            Zero std (degenerate window) is treated as a no-op:
            the detector reports ``detected=False``.
    """

    detected: bool
    z_score: float
    current_value: float
    window_mean: float
    window_std: float
