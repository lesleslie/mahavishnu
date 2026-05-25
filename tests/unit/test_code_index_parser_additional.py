"""Additional tests for the code-index parser."""

from __future__ import annotations

import datetime as _datetime
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

import mahavishnu.core.code_index.parser as parser
from mahavishnu.core.code_index.models import CodeGraphEdge, CodeGraphNode


for _model in (CodeGraphNode, CodeGraphEdge):
    _model.model_rebuild(_types_namespace={"datetime": _datetime.datetime})


class _FakeAnalyzer:
    def __init__(self, repo_path):
        self.repo_path = repo_path
        self.nodes = {}

    async def _analyze_python_file(self, path):
        self.nodes = {
            "function": SimpleNamespace(
                node_type="function",
                name="foo",
                docstring="secret-token",
                complexity=3,
                start_line=2,
                end_line=8,
                calls=["bar"],
            ),
            "class": SimpleNamespace(
                node_type="class",
                name="Baz",
                start_line=10,
                end_line=20,
            ),
            "import": SimpleNamespace(
                node_type="import",
                name="ignored",
                module="os",
            ),
            "unknown": SimpleNamespace(
                node_type="unknown",
                name="skip-me",
            ),
        }


def _install_fake_mcp_common(monkeypatch):
    analyzer_mod = ModuleType("mcp_common.code_graph.analyzer")
    analyzer_mod.CodeGraphAnalyzer = _FakeAnalyzer

    code_graph_mod = ModuleType("mcp_common.code_graph")
    code_graph_mod.analyzer = analyzer_mod

    mcp_common_mod = ModuleType("mcp_common")
    mcp_common_mod.code_graph = code_graph_mod

    monkeypatch.setitem(sys.modules, "mcp_common", mcp_common_mod)
    monkeypatch.setitem(sys.modules, "mcp_common.code_graph", code_graph_mod)
    monkeypatch.setitem(sys.modules, "mcp_common.code_graph.analyzer", analyzer_mod)


def test_parse_file_success_builds_nodes_and_edges(tmp_path, monkeypatch):
    _install_fake_mcp_common(monkeypatch)
    monkeypatch.setattr(parser, "redact_signature", lambda docstring: f"redacted:{docstring}")
    source = tmp_path / "sample.py"
    source.write_text("def foo():\n    pass\n")

    nodes, edges = parser.parse_file(str(source), str(tmp_path), "abc123")

    assert len(nodes) == 2
    assert {node.symbol_type for node in nodes} == {"function", "class"}
    assert nodes[0].signature == "redacted:secret-token"
    assert nodes[0].complexity == 3
    assert nodes[1].symbol_name == "Baz"
    assert len(edges) == 2
    assert {edge.edge_type for edge in edges} == {"calls", "imports"}


def test_parse_file_raises_on_analyzer_failure(tmp_path, monkeypatch):
    class _BoomAnalyzer:
        def __init__(self, repo_path):
            self.repo_path = repo_path

        async def _analyze_python_file(self, path):
            raise RuntimeError("boom")

    analyzer_mod = ModuleType("mcp_common.code_graph.analyzer")
    analyzer_mod.CodeGraphAnalyzer = _BoomAnalyzer
    code_graph_mod = ModuleType("mcp_common.code_graph")
    code_graph_mod.analyzer = analyzer_mod
    mcp_common_mod = ModuleType("mcp_common")
    mcp_common_mod.code_graph = code_graph_mod
    monkeypatch.setitem(sys.modules, "mcp_common", mcp_common_mod)
    monkeypatch.setitem(sys.modules, "mcp_common.code_graph", code_graph_mod)
    monkeypatch.setitem(sys.modules, "mcp_common.code_graph.analyzer", analyzer_mod)

    source = tmp_path / "sample.py"
    source.write_text("def foo():\n    pass\n")

    with pytest.raises(RuntimeError, match="boom"):
        parser.parse_file(str(source), str(tmp_path), "abc123")


def test_filter_changed_files_commit_based_filters_non_python(tmp_path, monkeypatch):
    fake_result = MagicMock()
    fake_result.stdout = "a.py\nb.txt\nsubdir/c.py\n"
    monkeypatch.setattr(parser.subprocess, "run", lambda *args, **kwargs: fake_result)

    result = parser.filter_changed_files(str(tmp_path), "abc123")

    assert result == [str(tmp_path / "a.py"), str(tmp_path / "subdir/c.py")]


def test_parse_file_skips_python_file_in_skip_dir(tmp_path):
    source = tmp_path / "node_modules" / "sample.py"
    source.parent.mkdir()
    source.write_text("def foo():\n    pass\n")

    assert parser.parse_file(str(source), str(tmp_path), "abc123") is None
