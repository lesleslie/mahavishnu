"""Substring scorer (REQ-EVAL-002).

Scores ``1.0`` when the actual output contains the expected substring,
and ``0.0`` otherwise.

**Why this scorer exists.** The dogfood golden set
(``docs/eval/dogfood-v0.jsonl``) is a set of questions about
Mahavishnu whose answers are *phrases*, not strings: the expected
value for "which pool selector minimizes latency?" is
``"least_loaded"``, and a correct answer might be "Use
``least_loaded`` because ...". :class:`~mahavishnu.core.eval.scorers.exact_match.ExactMatchScorer`
scores that as zero, always.

Substring matching is the honest middle ground between exact match and
an LLM judge: it rewards an answer that contains the expected phrase
and ignores the surrounding prose, without a second model call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mahavishnu.core.eval.scorer import Score, Scorer

if TYPE_CHECKING:
    from collections.abc import Mapping


class ContainsScorer(Scorer):
    """Scores whether the actual output contains the expected substring."""

    name = "mahavishnu.contains"
    kind = "contains"

    def __init__(self, case_sensitive: bool = False) -> None:
        """Configure the scorer.

        Args:
            case_sensitive: When ``True``, both sides are compared
                byte-for-byte. The default is ``False``: an answer that
                capitalises a selector name is still correct.
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
            expected: The phrase the output must contain.
            case_meta: The case's metadata. Unused by this scorer.

        Returns:
            ``1.0`` when the output contains the phrase, ``0.0``
            otherwise, with a reason describing the miss.
        """
        if not expected:
            # An empty expectation would match everything, which is a
            # silently-passing case rather than a score.
            return Score(
                value=0.0,
                kind=self.kind,
                reasoning="expected phrase is empty; nothing to match",
            )
        left, right = actual, expected
        if not self.case_sensitive:
            left, right = left.casefold(), right.casefold()
        matched = right in left
        return Score(
            value=1.0 if matched else 0.0,
            kind=self.kind,
            reasoning=None if matched else f"output does not contain {expected!r}",
        )


__all__ = ["ContainsScorer"]
