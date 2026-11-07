"""Exact-match scorer (REQ-EVAL-002).

Scores ``1.0`` when the actual output equals the expected output, and
``0.0`` otherwise. This is the baseline scorer: it is exact, it is
obvious to a human reading the report, and it cannot be gamed by a model
that writes more.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mahavishnu.core.eval.scorer import Score, Scorer

if TYPE_CHECKING:
    from collections.abc import Mapping


class ExactMatchScorer(Scorer):
    """Scores an exact match between the actual and expected output."""

    name = "mahavishnu.exact_match"
    kind = "exact_match"

    def __init__(self, case_sensitive: bool = True) -> None:
        """Configure the scorer.

        Args:
            case_sensitive: When ``False``, both sides are case-folded
                before comparison.
        """
        self.case_sensitive = case_sensitive

    def score(
        self,
        actual: str,
        expected: str,
        case_meta: Mapping[str, Any],
    ) -> Score:
        """Score one case.

        Args:
            actual: The model's output for the case.
            expected: The expected output for the case.
            case_meta: The case's metadata. Unused by this scorer.

        Returns:
            ``1.0`` on an exact match, ``0.0`` otherwise, with a reason
            describing the mismatch.
        """
        left, right = actual, expected
        if not self.case_sensitive:
            left, right = left.casefold(), right.casefold()
        matched = left == right
        return Score(
            value=1.0 if matched else 0.0,
            kind=self.kind,
            reasoning=None if matched else f"expected {expected!r}, got {actual!r}",
        )
