"""Contract tests for the exact-match scorer (REQ-EVAL-002).

Validates:

- an exact match scores 1.0 and a mismatch scores 0.0;
- ``case_sensitive=False`` folds case before comparing;
- a score outside the unit interval is refused;
- the scorer is discoverable through the registry.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from mahavishnu.core.eval._registry import discover_scorers
from mahavishnu.core.eval.scorer import Score
from mahavishnu.core.eval.scorers.exact_match import ExactMatchScorer


@pytest.mark.req(["REQ-EVAL-002"])
def test_matching_output_scores_one() -> None:
    """Identical actual and expected output scores 1.0."""
    score = ExactMatchScorer().score(actual="hello", expected="hello", case_meta={})
    assert score.value == 1.0
    assert score.kind == "exact_match"
    assert score.reasoning is None


@pytest.mark.req(["REQ-EVAL-002"])
def test_mismatched_output_scores_zero() -> None:
    """Different actual and expected output scores 0.0, with a reason."""
    score = ExactMatchScorer().score(actual="hi", expected="hello", case_meta={})
    assert score.value == 0.0
    assert score.reasoning is not None
    assert "hello" in score.reasoning


@pytest.mark.req(["REQ-EVAL-002"])
def test_case_insensitive_mode_folds_case() -> None:
    """case_sensitive=False ignores case differences but not content."""
    scorer = ExactMatchScorer(case_sensitive=False)
    assert scorer.score(actual="HELLO", expected="hello", case_meta={}).value == 1.0
    assert scorer.score(actual="Hi", expected="hello", case_meta={}).value == 0.0


@pytest.mark.req(["REQ-EVAL-002"])
def test_case_sensitive_is_the_default() -> None:
    """The default is case-sensitive."""
    score = ExactMatchScorer().score(actual="HELLO", expected="hello", case_meta={})
    assert score.value == 0.0


@pytest.mark.req(["REQ-EVAL-002"])
def test_score_value_must_be_within_the_unit_interval() -> None:
    """A score outside [0, 1] is refused."""
    with pytest.raises(ValidationError):
        Score(value=1.5, kind="exact_match")


@pytest.mark.req(["REQ-EVAL-002"])
def test_scorer_is_discoverable() -> None:
    """The exact-match scorer is discoverable through the registry."""
    assert discover_scorers()["mahavishnu.exact_match"] is ExactMatchScorer
