"""Tests for code graph Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mahavishnu.core.code_index.models import (
    CallChain,
    CallChainRequest,
    CallChainResult,
    CodeGraphEdge,
    CodeGraphNode,
    DegradationTier,
    ImpactAnalysisRequest,
    ImpactAnalysisResult,
    IndexWorkItem,
    SymbolImpact,
)


class TestCodeGraphNode:
    """Tests for CodeGraphNode."""

    def test_required_fields(self):
        """All required fields are accepted."""
        node = CodeGraphNode(
            symbol_id="repo|||file|||function|||foo",
            symbol_name="foo",
            symbol_type="function",
            file_path="foo.py",
            repo_path="/repo",
            last_indexed_at=datetime.now(UTC),
            commit_hash="abc123",
        )
        assert node.symbol_id == "repo|||file|||function|||foo"
        assert node.symbol_type == "function"
        assert node.is_deleted is False

    def test_optional_fields_default(self):
        node = CodeGraphNode(
            symbol_id="repo|||file|||function|||foo",
            symbol_name="foo",
            symbol_type="function",
            file_path="foo.py",
            repo_path="/repo",
            last_indexed_at=datetime.now(UTC),
            commit_hash="abc123",
        )
        assert node.start_line is None
        assert node.end_line is None
        assert node.signature is None
        assert node.complexity is None
        assert node.language == "python"

    def test_symbol_type_validation(self):
        """Only allowed symbol types are accepted."""
        CodeGraphNode(
            symbol_id="x",
            symbol_name="x",
            symbol_type="function",
            file_path="x.py",
            repo_path="/x",
            last_indexed_at=datetime.now(UTC),
            commit_hash="x",
        )
        CodeGraphNode(
            symbol_id="x",
            symbol_name="x",
            symbol_type="class",
            file_path="x.py",
            repo_path="/x",
            last_indexed_at=datetime.now(UTC),
            commit_hash="x",
        )
        with pytest.raises(ValidationError):
            CodeGraphNode(
                symbol_id="x",
                symbol_name="x",
                symbol_type="unknown",
                file_path="x.py",
                repo_path="/x",
                last_indexed_at=datetime.now(UTC),
                commit_hash="x",
            )


class TestCodeGraphEdge:
    """Tests for CodeGraphEdge."""

    def test_required_fields(self):
        edge = CodeGraphEdge(
            source="a",
            target="b",
            edge_type="calls",
            source_file="a.py",
            target_file="b.py",
            repo_path="/repo",
            created_at=datetime.now(UTC),
        )
        assert edge.confidence == 1.0

    def test_edge_type_validation(self):
        with pytest.raises(ValidationError):
            CodeGraphEdge(
                source="a",
                target="b",
                edge_type="invalid",
                source_file="a.py",
                target_file="b.py",
                repo_path="/repo",
                created_at=datetime.now(UTC),
            )


class TestCallChainRequest:
    """Tests for CallChainRequest."""

    def test_defaults(self):
        req = CallChainRequest(symbol_name="foo")
        assert req.direction == "both"
        assert req.max_depth == 5
        assert req.repo_path is None
        assert req.edge_filter is None

    def test_max_depth_clamped_to_10(self):
        req = CallChainRequest(symbol_name="foo", max_depth=10)
        assert req.max_depth == 10

    def test_max_depth_over_10_raises(self):
        with pytest.raises(ValidationError, match="max_depth cannot exceed 10"):
            CallChainRequest(symbol_name="foo", max_depth=11)


class TestCallChain:
    """Tests for CallChain."""

    def test_fields(self):
        chain = CallChain(
            path=["a", "b", "c"],
            depth=2,
            edge_types=["calls", "imports"],
            files=["a.py", "b.py", "c.py"],
        )
        assert chain.depth == 2


class TestCallChainResult:
    """Tests for CallChainResult."""

    def test_defaults(self):
        result = CallChainResult(
            root_symbol="foo",
            chains=[],
            total_nodes=0,
        )
        assert result.truncated is False
        assert result.stale is False
        assert result.last_indexed_at is None


class TestImpactAnalysisRequest:
    """Tests for ImpactAnalysisRequest."""

    def test_defaults(self):
        req = ImpactAnalysisRequest(symbol_name="foo")
        assert req.include_indirect is True
        assert req.max_depth == 5
        assert req.repo_path is None

    def test_max_depth_over_10_raises(self):
        with pytest.raises(ValidationError, match="max_depth cannot exceed 10"):
            ImpactAnalysisRequest(symbol_name="foo", max_depth=15)


class TestImpactAnalysisResult:
    """Tests for ImpactAnalysisResult."""

    def test_fields(self):
        result = ImpactAnalysisResult(
            target="foo",
            direct_dependents=[],
            indirect_dependents=[],
            affected_files=[],
            risk_level="medium",
            blast_radius=0,
        )
        assert result.risk_level in ("low", "medium", "high")


class TestIndexWorkItem:
    """Tests for IndexWorkItem."""

    def test_status_values(self):
        item = IndexWorkItem(
            repo_path="/repo",
            trigger="manual",
            files_changed=[],
            status="parsing",
        )
        assert item.status == "parsing"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            IndexWorkItem(
                repo_path="/repo",
                trigger="manual",
                files_changed=[],
                status="invalid_status",
            )

    def test_trigger_values(self):
        item = IndexWorkItem(
            repo_path="/repo",
            trigger="git-event",
            files_changed=[],
            status="queued",
        )
        assert item.trigger == "git-event"

    def test_invalid_trigger_rejected(self):
        with pytest.raises(ValidationError):
            IndexWorkItem(
                repo_path="/repo",
                trigger="invalid_trigger",
                files_changed=[],
                status="queued",
            )

    def test_parse_failures_default_zero(self):
        item = IndexWorkItem(
            repo_path="/repo",
            trigger="manual",
            files_changed=[],
            status="queued",
        )
        assert item.parse_failures == 0


class TestSymbolImpact:
    """Tests for SymbolImpact."""

    def test_fields(self):
        impact = SymbolImpact(
            symbol_name="foo",
            symbol_type="function",
            file_path="foo.py",
            depth=1,
            dependency_type="calls",
        )
        assert impact.depth == 1


class TestDegradationTier:
    """Tests for DegradationTier."""

    def test_tier_values(self):
        tier = DegradationTier(tier=1, reason="full")
        assert tier.tier == 1

    def test_invalid_tier_rejected(self):
        with pytest.raises(ValidationError):
            DegradationTier(tier=5, reason="invalid")  # only 1-4 allowed