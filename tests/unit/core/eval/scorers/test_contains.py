"""Contract tests for the contains scorer (REQ-EVAL-002).

The contains scorer is what makes the dogfood golden set gradeable: the
expected value for "which pool selector minimizes latency?" is a
phrase (``least_loaded``), not the whole answer.
"""

from __future__ import annotations

import pytest

from mahavishnu.core.eval._registry import discover_scorers
from mahavishnu.core.eval.scorers.contains import ContainsScorer

# req: REQ-EVAL-002


@pytest.mark.req(["REQ-EVAL-002"])
def test_a_contained_phrase_scores_one() -> None:
    """An output that contains the phrase scores 1.0."""
    score = ContainsScorer().score(
        "Use least_loaded because the pool is saturated.",
        "least_loaded",
        {},
    )
    assert score.value == 1.0
    assert score.kind == "contains"
    assert score.reasoning is None


@pytest.mark.req(["REQ-EVAL-002"])
def test_a_missing_phrase_scores_zero_with_a_reason() -> None:
    """An output that does not contain the phrase scores 0.0."""
    score = ContainsScorer().score("Use round_robin.", "least_loaded", {})
    assert score.value == 0.0
    assert score.reasoning is not None
    assert "least_loaded" in score.reasoning


@pytest.mark.req(["REQ-EVAL-002"])
def test_matching_is_case_insensitive_by_default() -> None:
    """A differently-cased phrase still matches by default."""
    score = ContainsScorer().score("Use LEAST_LOADED here.", "least_loaded", {})
    assert score.value == 1.0


@pytest.mark.req(["REQ-EVAL-002"])
def test_case_sensitivity_can_be_required() -> None:
    """A case-sensitive scorer rejects a differently-cased phrase."""
    scorer = ContainsScorer(case_sensitive=True)
    assert scorer.score("Use LEAST_LOADED here.", "least_loaded", {}).value == 0.0
    assert scorer.score("Use least_loaded here.", "least_loaded", {}).value == 1.0


@pytest.mark.req(["REQ-EVAL-002"])
def test_an_empty_expectation_scores_zero() -> None:
    """An empty expectation matches nothing rather than everything."""
    score = ContainsScorer().score("anything", "", {})
    assert score.value == 0.0
    assert score.reasoning is not None


@pytest.mark.req(["REQ-EVAL-002"])
def test_the_scorer_is_discoverable() -> None:
    """The contains scorer is registered under its published name."""
    assert discover_scorers()["mahavishnu.contains"] is ContainsScorer
