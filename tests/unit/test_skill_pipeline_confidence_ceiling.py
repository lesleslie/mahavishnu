"""Spec #3 wiring: confidence ceiling applied to distiller output.

The distiller's output stage produces confidence-bearing dict records.
The :func:`cap_distiller_output` consumer applies the Spec #3 ceiling
before records leave the distiller, so downstream consumers (audit log,
persistence, MCP tools) never see over-confident self-reports.

This file is the wiring test; the gate itself is fully exercised in
``test_confidence_ceiling.py``.
"""

from __future__ import annotations

import pytest

from mahavishnu.core.events.confidence_ceiling import (
    apply_confidence_ceiling,
    get_confidence_ceiling_cap,
)
from mahavishnu.distill.consumer import cap_distiller_output


def _record(confidence: int, open_q: int = 0, unchecked: int = 0) -> dict:
    return {
        "confidence": confidence,
        "open_questions": [f"q{i}" for i in range(open_q)],
        "unchecked_sources": [f"s{i}" for i in range(unchecked)],
        "skill_name": "example.skill",
        "from_zone": "intake",
        "to_zone": "transform",
    }


# ---------------------------------------------------------------------------
# cap_distiller_output — the wiring function
# ---------------------------------------------------------------------------


def test_distiller_passthrough_when_within_cap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAHAVISHNU_CONFIDENCE_CEILING", raising=False)
    record = _record(confidence=80, open_q=0, unchecked=0)
    result = cap_distiller_output(record)
    # 80 <= 85 (default env cap) -> passthrough.
    assert result is record
    assert result["confidence"] == 80


def test_distiller_caps_over_confidence_to_env_cap(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("MAHAVISHNU_CONFIDENCE_CEILING", raising=False)
    record = _record(confidence=99, open_q=0, unchecked=0)
    result = cap_distiller_output(record)
    # 99 > 85 default env cap -> capped.
    assert result is not record
    assert result["confidence"] == 85


def test_distiller_caps_via_env_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "0.50")  # 50
    record = _record(confidence=80, open_q=0, unchecked=0)
    result = cap_distiller_output(record)
    assert result["confidence"] == 50


def test_distiller_preserves_other_fields(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAHAVISHNU_CONFIDENCE_CEILING", raising=False)
    record = _record(confidence=99, open_q=0, unchecked=0)
    result = cap_distiller_output(record)
    # All non-confidence fields must be preserved on the capped copy.
    assert result["skill_name"] == "example.skill"
    assert result["from_zone"] == "intake"
    assert result["to_zone"] == "transform"
    assert isinstance(result["open_questions"], list)
    assert isinstance(result["unchecked_sources"], list)


def test_distiller_structural_cap_wins_when_lower(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAHAVISHNU_CONFIDENCE_CEILING", "0.99")  # 99
    # 3 open questions -> structural cap = 76; reported 90 > 76 -> capped to 76.
    record = _record(confidence=90, open_q=3, unchecked=0)
    result = cap_distiller_output(record)
    assert result["confidence"] == 76


def test_distiller_structural_cap_floors_at_zero():
    record = _record(confidence=99, open_q=13, unchecked=1)
    result = cap_distiller_output(record)
    assert result["confidence"] == 0


def test_distiller_does_not_raise_when_capping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAHAVISHNU_CONFIDENCE_CEILING", raising=False)
    # Absurd reported value must not raise; calibration, not rule.
    record = _record(confidence=99999)
    result = cap_distiller_output(record)
    assert result["confidence"] == 85


def test_distiller_no_op_when_no_open_questions_and_env_cap_default():
    record = _record(confidence=100, open_q=0, unchecked=0)
    result = cap_distiller_output(record)
    # 100 > 85 default cap -> capped to 85 (env cap still binds).
    assert result["confidence"] == 85


def test_distiller_within_structural_and_env_returns_reference():
    # No open questions + default env cap = 85. Reported 50 is within.
    record = _record(confidence=50, open_q=0, unchecked=0)
    result = cap_distiller_output(record)
    assert result is record


def test_apply_confidence_ceiling_directly_consistent_with_distiller():
    """Sanity: the standalone gate and the distiller consumer return identical
    results for identical inputs."""
    record = _record(confidence=95)
    direct = apply_confidence_ceiling(record)
    via_distiller = cap_distiller_output(record)
    assert direct["confidence"] == via_distiller["confidence"]


def test_distiller_consistent_with_get_confidence_ceiling_cap_default():
    """The wiring returns the default env cap when no open questions exist
    and the reported value exceeds the env cap."""
    record = _record(confidence=200)
    result = cap_distiller_output(record)
    assert result["confidence"] == get_confidence_ceiling_cap()
