"""Tests for the confidence ceiling gate (Spec #3).

Pure-function cap on reported confidence based on enumerable doubt
(open_questions, unchecked_sources). Caps do not raise; over-confidence
is calibration, not a rule violation.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from mahavishnu.core.events.confidence_ceiling import (
    OPEN_QUESTION_PENALTY,
    UNCHECKED_SOURCE_PENALTY,
    apply_confidence_ceiling,
    compute_confidence_cap,
    get_confidence_ceiling_cap,
)

if TYPE_CHECKING:
    import pytest


def _report(confidence: int = 0, open_q: int = 0, unchecked: int = 0) -> dict:
    return {
        "confidence": confidence,
        "open_questions": [f"q{i}" for i in range(open_q)],
        "unchecked_sources": [f"s{i}" for i in range(unchecked)],
    }


# ---------------------------------------------------------------------------
# compute_confidence_cap (pure)
# ---------------------------------------------------------------------------


def test_compute_cap_no_questions_no_sources():
    assert compute_confidence_cap(_report()) == 100


def test_compute_cap_one_open_question():
    assert compute_confidence_cap(_report(open_q=1)) == 92


def test_compute_cap_one_unchecked_source():
    assert compute_confidence_cap(_report(unchecked=1)) == 95


def test_compute_cap_mixed():
    assert compute_confidence_cap(_report(open_q=5, unchecked=5)) == 35


def test_compute_cap_floor_zero():
    assert compute_confidence_cap(_report(open_q=13, unchecked=1)) == 0


def test_compute_cap_missing_arrays_defaults_to_empty():
    report: dict = {"confidence": 50}
    assert compute_confidence_cap(report) == 100


def test_compute_cap_returns_int_in_range():
    cap = compute_confidence_cap(_report(open_q=100, unchecked=100))
    assert isinstance(cap, int)
    assert 0 <= cap <= 100


def test_compute_cap_with_workflow_metadata_fields():
    # When the report carries workflow metadata, the cap is unaffected.
    report = {
        "workflow_id": "wf-1",
        "iteration_index": 2,
        "confidence": 99,
        "open_questions": ["a"],
        "unchecked_sources": [],
    }
    assert compute_confidence_cap(report) == 92


# ---------------------------------------------------------------------------
# apply_confidence_ceiling (returns capped copy OR same reference)
# ---------------------------------------------------------------------------


def test_apply_ceiling_within_cap_returns_unchanged_reference():
    report = _report(confidence=80, open_q=2)
    result = apply_confidence_ceiling(report)
    assert result is report
    assert result["confidence"] == 80


def test_apply_ceiling_above_cap_returns_capped_copy():
    report = _report(confidence=99, open_q=2)
    result = apply_confidence_ceiling(report)
    assert result is not report
    assert result["confidence"] == 84  # 100 - 2*8
    assert report["confidence"] == 99  # original unchanged


def test_apply_ceiling_at_exact_cap_returns_unchanged_reference():
    report = _report(confidence=84, open_q=2)
    result = apply_confidence_ceiling(report)
    assert result is report
    assert result["confidence"] == 84


def test_apply_ceiling_logs_warning_when_capping(monkeypatch: pytest.MonkeyPatch):
    # Oneiric configures structlog with its own handlers, so pytest's
    # caplog doesn't capture its output. Patch the module-level logger
    # directly to assert the warning is emitted with the right text.
    import mahavishnu.core.events.confidence_ceiling as cc_mod

    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        cc_mod.logger,
        "warning",
        lambda msg, **kw: warnings.append((msg, kw)),
    )

    report = _report(confidence=99, open_q=3)
    result = apply_confidence_ceiling(report)
    assert result["confidence"] == 76  # 100 - 3*8
    assert any("confidence capped" in msg.lower() for msg, _ in warnings)


def test_apply_ceiling_warning_includes_metadata(monkeypatch: pytest.MonkeyPatch):
    import mahavishnu.core.events.confidence_ceiling as cc_mod

    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        cc_mod.logger,
        "warning",
        lambda msg, **kw: warnings.append((msg, kw)),
    )

    report = _report(confidence=99, open_q=3)
    apply_confidence_ceiling(report)
    assert warnings, "expected a warning when capping occurs"
    msg, kwargs = warnings[0]
    # structlog wraps kwargs as `extra=...` rather than passing them
    # positionally; unwrap to find the structural metadata.
    extra = kwargs.get("extra", kwargs)
    assert extra.get("reported_confidence") == 99
    assert extra.get("computed_cap") == 76
    assert extra.get("open_questions_count") == 3
    assert extra.get("unchecked_sources_count") == 0


def test_apply_ceiling_no_log_when_within_cap(monkeypatch: pytest.MonkeyPatch):
    import mahavishnu.core.events.confidence_ceiling as cc_mod

    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        cc_mod.logger,
        "warning",
        lambda msg, **kw: warnings.append((msg, kw)),
    )

    report = _report(confidence=80, open_q=2)
    result = apply_confidence_ceiling(report)
    assert result is report
    assert not warnings


def test_apply_ceiling_does_not_raise_when_capping():
    # Caps do not raise; over-confidence is calibration, not a rule violation.
    report = _report(confidence=999, open_q=3)
    # Should not raise even with absurdly high reported confidence.
    result = apply_confidence_ceiling(report)
    assert result["confidence"] == 76


def test_apply_ceiling_uses_configured_cap_when_lower(
    monkeypatch: pytest.MonkeyPatch,
):
    """When MAHAVISHNU_CONFIDENCE_CEILING env var lowers the cap below the
    structural cap, the env var value is applied."""
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "0.50")  # 50
    report = _report(confidence=80, open_q=2)
    result = apply_confidence_ceiling(report)
    # Structural cap = 100 - 2*8 = 84; env cap = 50. Reported 80 > 50, capped to 50.
    assert result is not report
    assert result["confidence"] == 50


def test_apply_ceiling_structural_cap_wins_when_lower(
    monkeypatch: pytest.MonkeyPatch,
):
    """When the env var is higher than the structural cap, the structural cap wins."""
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "0.99")  # 99
    report = _report(confidence=99, open_q=2)
    result = apply_confidence_ceiling(report)
    # Structural cap = 84; env cap = 99. Reported 99 > 84, capped to 84.
    assert result["confidence"] == 84


def test_apply_ceiling_caps_to_zero_when_structural_floor():
    report = _report(confidence=99, open_q=13, unchecked=1)
    result = apply_confidence_ceiling(report)
    assert result["confidence"] == 0


# ---------------------------------------------------------------------------
# Env var driven cap retrieval
# ---------------------------------------------------------------------------


def test_get_confidence_ceiling_cap_default():
    # Clear any pre-set env var to test the default.
    os.environ.pop("MAHAVISHNU_CONFIDENCE_CEILING", None)
    assert get_confidence_ceiling_cap() == 85


def test_get_confidence_ceiling_cap_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "0.70")
    assert get_confidence_ceiling_cap() == 70


def test_get_confidence_ceiling_cap_invalid_uses_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "not-a-number")
    assert get_confidence_ceiling_cap() == 85


def test_get_confidence_ceiling_cap_clamps_out_of_range(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "1.5")  # 150, clamped to 100
    assert get_confidence_ceiling_cap() == 100
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "-0.5")  # -50, clamped to 0
    assert get_confidence_ceiling_cap() == 0


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_penalty_constants_match_spec():
    # Spec: OPEN_QUESTION_PENALTY = 8, UNCHECKED_SOURCE_PENALTY = 5.
    assert OPEN_QUESTION_PENALTY == 8
    assert UNCHECKED_SOURCE_PENALTY == 5
