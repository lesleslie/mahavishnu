"""Shared severity classification for change-point detectors.

Single source of truth for the score → severity mapping used by both
the ``changepoint`` package (which must not import from the
``mahavishnu.core.observability`` orchestrator to avoid a cycle) and
the orchestrator's emission path.

Mirrors ``ObservabilityManager._classify_drift_severity`` contract:
``score >= 4*threshold`` → ``"critical"``; ``>= 2*threshold`` →
``"moderate"``; otherwise ``"minor"``.
"""
from __future__ import annotations


def classify_severity(score: float, threshold: float) -> str:
    """Classify drift severity by score/threshold ratio.

    Args:
        score: detector score for the current observation.
        threshold: detector threshold used to qualify a fire.

    Returns:
        One of ``"minor"``, ``"moderate"``, ``"critical"``.
    """
    if score >= 4 * threshold:
        return "critical"
    if score >= 2 * threshold:
        return "moderate"
    return "minor"


__all__ = ["classify_severity"]