"""Freshness check for the dogfood golden set (REQ-EVAL-007).

A golden set nobody re-reads is a golden set that certifies the wrong
thing. This test runs on every PR and fails when fewer than 80% of the
cases have been reviewed within the last 90 days.

It is deliberately cheap — it reads the JSONL file and parses the
metadata; it does not run a model or touch the run store — so it can
live in the fast gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pytest

# req: REQ-EVAL-007

#: The golden set, relative to the repository root.
GOLDEN_SET = Path("docs/eval/dogfood-v0.jsonl")

#: How old a review may be before the case counts as stale.
MAX_REVIEW_AGE = timedelta(days=90)

#: The fraction of cases that must be fresh.
MIN_FRESH_FRACTION = 0.80


def _repo_root() -> Path:
    """Return the repository root.

    ``mahavishnu/__init__.py`` -> parents[0] is the package directory,
    parents[1] is the repository root.
    """
    import mahavishnu

    return Path(mahavishnu.__file__).resolve().parents[1]


def _load_cases(path: Path) -> list[dict[str, Any]]:
    """Load the golden set's cases.

    Args:
        path: The JSONL file.

    Returns:
        The parsed cases.
    """
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            cases.append(json.loads(stripped))
    return cases


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-007"])
def test_the_golden_set_exists_and_has_enough_cases() -> None:
    """The golden set carries between 20 and 40 cases."""
    path = _repo_root() / GOLDEN_SET
    assert path.exists(), f"the golden set is missing: {path}"
    cases = _load_cases(path)
    assert 20 <= len(cases) <= 40, f"expected 20-40 cases, found {len(cases)}"


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-007"])
def test_every_case_is_well_formed() -> None:
    """Every case carries the fields the loader and the scorer need."""
    cases = _load_cases(_repo_root() / GOLDEN_SET)
    seen_ids: set[str] = set()
    for case in cases:
        assert set(case) == {"id", "input", "expected", "metadata"}, case.get("id")
        assert case["id"] not in seen_ids, f"duplicate case id {case['id']!r}"
        seen_ids.add(case["id"])
        assert case["input"].strip(), f"case {case['id']!r} has an empty question"
        assert case["expected"].strip(), f"case {case['id']!r} has an empty expectation"
        metadata = case["metadata"]
        assert metadata["added_by"].strip()
        assert metadata["failure_mode"].strip()
        assert metadata["last_reviewed"].strip()


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-007"])
def test_no_expectation_is_contained_in_its_own_question() -> None:
    """A case must not grade a phrase its own question already contains.

    A golden set grades the answer, not the echo of the question. If
    the expected phrase appears in the question, then the mock
    backend -- which echoes the prompt back -- scores the case 1.0
    without knowing anything, and a plausible *wrong* answer that
    quotes the question back scores it too. The set's own rule (see
    ``docs/eval/dogfood-v0.README.md``) is the shortest phrase a wrong
    answer would not contain; this test is the mechanical check for
    the sharpest version of that mistake.
    """
    cases = _load_cases(_repo_root() / GOLDEN_SET)
    self_contained = [
        (case["id"], case["expected"])
        for case in cases
        if case["expected"].lower() in case["input"].lower()
    ]
    assert not self_contained, (
        "these cases grade a phrase their own question contains: "
        f"{self_contained}"
    )


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-007"])
def test_every_reference_answer_would_score_one() -> None:
    """A case's known-correct answer must score 1.0 under the default scorer.

    The self-containment test covers the *false-positive* direction: an
    expectation that its own question contains is satisfied by the
    mock's echo. This covers the other direction: an expectation so
    strict that no correct answer would contain it scores a correct
    answer 0.0. A case may carry a ``metadata.reference`` -- a
    known-correct answer -- and every such case must be gradeable.
    """
    from mahavishnu.core.eval.scorers.contains import ContainsScorer

    scorer = ContainsScorer()
    cases = _load_cases(_repo_root() / GOLDEN_SET)
    ungradeable = [
        case["id"]
        for case in cases
        if "reference" in case["metadata"]
        and scorer.score(
            case["metadata"]["reference"],
            case["expected"],
            case["metadata"],
        ).value
        != 1.0
    ]
    assert not ungradeable, (
        "these cases' reference answers do not score 1.0, so their "
        f"expectations are too strict to be met: {ungradeable}"
    )


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-007"])
def test_at_least_eighty_percent_of_cases_are_fresh() -> None:
    """At least 80% of the cases were reviewed within the last 90 days."""
    cases = _load_cases(_repo_root() / GOLDEN_SET)
    cutoff = datetime.now(UTC) - MAX_REVIEW_AGE

    fresh = 0
    stale: list[str] = []
    for case in cases:
        reviewed_raw = case["metadata"]["last_reviewed"]
        reviewed = datetime.fromisoformat(reviewed_raw)
        if reviewed.tzinfo is None:
            reviewed = reviewed.replace(tzinfo=UTC)
        if reviewed >= cutoff:
            fresh += 1
        else:
            stale.append(case["id"])

    fraction = fresh / len(cases)
    assert fraction >= MIN_FRESH_FRACTION, (
        f"only {fresh}/{len(cases)} ({fraction:.0%}) of the golden set was "
        f"reviewed within {MAX_REVIEW_AGE.days} days; stale cases: {stale}"
    )
