"""Additional tests for code-index Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from mahavishnu.core.code_index.models import (
    CallChainRequest,
    CodeGraphEdge,
    CodeGraphNode,
    DegradationTier,
    ImpactAnalysisRequest,
    IndexWorkItem,
    SymbolImpact,
)

for _model in (
    CodeGraphNode,
    CodeGraphEdge,
    CallChainRequest,
    ImpactAnalysisRequest,
    IndexWorkItem,
    SymbolImpact,
    DegradationTier,
):
    _model.model_rebuild(_types_namespace={"datetime": datetime})


class TestCodeIndexModelDefaults:
    """Exercise defaults that existing coverage does not hit directly."""

    def test_node_defaults_and_model_dump(self):
        node = CodeGraphNode(
            symbol_id="repo|||file|||module|||mod",
            symbol_name="mod",
            symbol_type="module",
            file_path="mod.py",
            repo_path="/repo",
            last_indexed_at=datetime.now(UTC),
            commit_hash="abc123",
        )

        payload = node.model_dump()
        assert payload["language"] == "python"
        assert payload["is_deleted"] is False
        assert payload["start_line"] is None

    def test_edge_defaults_and_model_dump(self):
        edge = CodeGraphEdge(
            source="a",
            target="b",
            edge_type="imports",
            source_file="a.py",
            target_file="b.py",
            repo_path="/repo",
            created_at=datetime.now(UTC),
        )

        payload = edge.model_dump()
        assert payload["confidence"] == 1.0

    def test_call_chain_request_defaults(self):
        req = CallChainRequest(symbol_name="foo")

        assert req.direction == "both"
        assert req.max_depth == 5
        assert req.repo_path is None
        assert req.edge_filter is None

    def test_call_chain_request_allows_max_depth_10(self):
        req = CallChainRequest(symbol_name="foo", max_depth=10)

        assert req.max_depth == 10

    def test_impact_analysis_request_defaults(self):
        req = ImpactAnalysisRequest(symbol_name="foo")

        assert req.include_indirect is True
        assert req.max_depth == 5
        assert req.repo_path is None

    def test_impact_analysis_request_allows_max_depth_10(self):
        req = ImpactAnalysisRequest(symbol_name="foo", max_depth=10)

        assert req.max_depth == 10

    def test_index_work_item_defaults(self):
        item = IndexWorkItem(
            repo_path="/repo",
            trigger="manual",
            files_changed=[],
            status="queued",
        )

        assert item.started_at is None
        assert item.completed_at is None
        assert item.parse_failures == 0

    def test_symbol_impact_validation(self):
        impact = SymbolImpact(
            symbol_name="foo",
            symbol_type="function",
            file_path="foo.py",
            depth=1,
            dependency_type="calls",
        )

        assert impact.dependency_type == "calls"

    def test_degradation_tier_default_counters(self):
        tier = DegradationTier(tier=4, reason="stale")

        assert tier.stale_since is None
        assert tier.parse_failures == 0
        assert tier.total_files == 0


class TestCodeIndexModelValidation:
    """Exercise validation branches and error messages."""

    def test_node_rejects_bad_symbol_type(self):
        with pytest.raises(ValidationError):
            CodeGraphNode(
                symbol_id="x",
                symbol_name="x",
                symbol_type="not-a-type",
                file_path="x.py",
                repo_path="/repo",
                last_indexed_at=datetime.now(UTC),
                commit_hash="abc",
            )

    def test_edge_rejects_bad_edge_type(self):
        with pytest.raises(ValidationError):
            CodeGraphEdge(
                source="a",
                target="b",
                edge_type="not-an-edge",
                source_file="a.py",
                target_file="b.py",
                repo_path="/repo",
                created_at=datetime.now(UTC),
            )

    def test_call_chain_request_rejects_excess_depth(self):
        with pytest.raises(ValidationError, match="max_depth cannot exceed 10"):
            CallChainRequest(symbol_name="foo", max_depth=11)

    def test_impact_analysis_request_rejects_excess_depth(self):
        with pytest.raises(ValidationError, match="max_depth cannot exceed 10"):
            ImpactAnalysisRequest(symbol_name="foo", max_depth=11)

    def test_index_work_item_rejects_bad_trigger(self):
        with pytest.raises(ValidationError):
            IndexWorkItem(
                repo_path="/repo",
                trigger="bad-trigger",
                files_changed=[],
                status="queued",
            )

    def test_index_work_item_rejects_bad_status(self):
        with pytest.raises(ValidationError):
            IndexWorkItem(
                repo_path="/repo",
                trigger="manual",
                files_changed=[],
                status="bad-status",
            )
