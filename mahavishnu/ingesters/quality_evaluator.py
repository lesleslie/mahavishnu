"""Compatibility wrapper for quality evaluation types.

.. deprecated:: 0.4.0
    This module is a re-export wrapper. Import directly from
    ``mahavishnu.ingesters.quality_scorer`` instead.

    To migrate, change imports from::

        from mahavishnu.ingesters.quality_evaluator import EvaluationReport, QualityMetric

    To::

        from mahavishnu.ingesters.quality_scorer import EvaluationReport, QualityMetric

This module will be removed in a future release.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "mahavishnu.ingesters.quality_evaluator is a compatibility wrapper. "
    "Import from mahavishnu.ingesters.quality_scorer instead. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from mahavishnu.ingesters.quality_scorer import (  # noqa: F401
    EvaluationReport,
    MetricScore,
    QualityMetric,
)

__all__ = [
    "QualityMetric",
    "MetricScore",
    "EvaluationReport",
]


def create_quality_evaluator(config: dict | None = None):
    """Create a quality evaluator instance.

    .. deprecated:: 0.4.0
        Use ``ContentQualityScorer`` from ``quality_scorer`` instead.
    """
    from mahavishnu.ingesters.quality_scorer import ContentQualityScorer

    return ContentQualityScorer()


class QualityEvaluator:
    """Quality evaluator for content.

    .. deprecated:: 0.4.0
        Use ``ContentQualityScorer`` from ``quality_scorer`` instead.
    """

    def __init__(self, config: dict | None = None):
        from mahavishnu.ingesters.quality_scorer import ContentQualityScorer

        self._scorer = ContentQualityScorer()
        self.config = config or {}

    def evaluate(self, content: str, content_id: str = "unknown") -> EvaluationReport:
        """Evaluate content quality."""
        return self._scorer.score(content, content_id=content_id)
