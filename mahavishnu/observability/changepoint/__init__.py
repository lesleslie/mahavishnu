"""Sequential change-point detectors for Mahavishnu observability (Tier 1 Phase 5).

# Implements: REQ-004

Exposes:

* :class:`~mahavishnu.observability.changepoint.cusum.CUSUMDetector` —
  Cumulative Sum (CUSUM) detector. One-sided and two-sided variants
  supported. Tunable slack (``k``) and threshold (``h``) parameters
  for the canonical Brook & Evans 1972 ARL₀ design.
* :class:`~mahavishnu.observability.changepoint.page_hinkley.PageHinkleyDetector` —
  Page-Hinkley test, the online-quadratic variant. Detects both
  upward and downward mean shifts.
* :class:`~mahavishnu.observability.changepoint.anomaly.AnomalyResult` —
  Dataclass holding a 3-sigma reference detector result, used in
  Phase 6 alongside the change-point detector as a fallback.

The library is pure-Python with no third-party dependencies and
integrates with :class:`mahavishnu.core.observability.ObservabilityManager`
in Phase 6.
"""

from __future__ import annotations

from mahavishnu.observability.changepoint.anomaly import AnomalyResult
from mahavishnu.observability.changepoint.cusum import (
    ChangePointDetector,
    ChangePointResult,
    CUSUMDetector,
)
from mahavishnu.observability.changepoint.page_hinkley import (
    PageHinkleyDetector,
)
from mahavishnu.observability.changepoint.two_stage import (
    TwoStageDetector,
    TwoStageResult,
    TwoStageState,
)

__all__ = [
    "AnomalyResult",
    "CUSUMDetector",
    "ChangePointDetector",
    "ChangePointResult",
    "PageHinkleyDetector",
    "TwoStageDetector",
    "TwoStageResult",
    "TwoStageState",
]
