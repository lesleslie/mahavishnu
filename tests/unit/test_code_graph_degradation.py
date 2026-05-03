"""Tests for code graph degradation tiers."""

import pytest

from mahavishnu.core.code_index.models import (
    CallChainRequest,
    CallChainResult,
    CodeGraphUnavailable,
    DegradationTier,
    ImpactAnalysisRequest,
    ImpactAnalysisResult,
)


def test_stale_flag_true_when_old():
    """Results include stale=True when index is > 24 hours old."""
    result = CallChainResult(
        root_symbol="test",
        chains=[],
        total_nodes=0,
        stale=True,
        last_indexed_at="2026-04-25T00:00:00Z",
    )
    assert result.stale is True


def test_stale_flag_false_when_fresh():
    """Results include stale=False when index is recent."""
    result = CallChainResult(
        root_symbol="test",
        chains=[],
        total_nodes=0,
        stale=False,
    )
    assert result.stale is False


def test_code_graph_unavailable_has_reason():
    unavailable = CodeGraphUnavailable(
        reason="DuckDB file corrupted",
        suggestion="Run mahavishnu index --repo <path> --full to re-index",
    )
    assert unavailable.tier == 4
    assert "corrupted" in unavailable.reason.lower()


def test_code_graph_unavailable_default_tier():
    unavailable = CodeGraphUnavailable(
        reason="unknown",
        suggestion="try again later",
    )
    assert unavailable.tier == 4  # default tier


def test_impact_result_risk_levels():
    low = ImpactAnalysisResult(
        target="test",
        direct_dependents=[],
        indirect_dependents=[],
        affected_files=[],
        risk_level="low",
        blast_radius=0,
    )
    assert low.risk_level == "low"


def test_impact_result_stale():
    stale = ImpactAnalysisResult(
        target="test",
        direct_dependents=[],
        indirect_dependents=[],
        affected_files=[],
        risk_level="medium",
        blast_radius=5,
        stale=True,
    )
    assert stale.stale is True


def test_degradation_tier_model():
    tier = DegradationTier(
        tier=2,
        reason="Partial index after crash",
        stale_since="2026-04-25T12:00:00Z",
        parse_failures=3,
        total_files=100,
    )
    assert tier.tier == 2
    assert tier.parse_failures == 3
    assert tier.total_files == 100


def test_max_depth_clamp():
    """max_depth > 10 is rejected by Pydantic validator."""
    with pytest.raises(ValueError, match="max_depth"):
        CallChainRequest(symbol_name="test", max_depth=20)
    with pytest.raises(ValueError, match="max_depth"):
        ImpactAnalysisRequest(symbol_name="test", max_depth=15)
