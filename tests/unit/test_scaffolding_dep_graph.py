"""Tests for pattern dependency graph utilities."""

from __future__ import annotations

import pytest

from mahavishnu.scaffolding.dependency_graph import (
    CircularDependencyError,
    PatternDependencyGraph,
)


class TestTopologicalSort:
    def test_simple_chain(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.add("c")
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        order = g.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond_dependency(self):
        g = PatternDependencyGraph()
        g.add("root")
        g.add("left")
        g.add("right")
        g.add("leaf")
        g.add_edge("root", "left")
        g.add_edge("root", "right")
        g.add_edge("left", "leaf")
        g.add_edge("right", "leaf")
        order = g.topological_sort()
        assert order.index("root") < order.index("left")
        assert order.index("root") < order.index("right")
        assert order.index("left") < order.index("leaf")
        assert order.index("right") < order.index("leaf")

    def test_alphabetical_secondary_sort(self):
        g = PatternDependencyGraph()
        g.add("z")
        g.add("a")
        g.add("m")
        order = g.topological_sort()
        assert order == ["a", "m", "z"]

    def test_circular_dependency_raises(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.add("c")
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "a")
        with pytest.raises(CircularDependencyError):
            g.topological_sort()

    def test_self_dependency_raises(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add_edge("a", "a")
        with pytest.raises(CircularDependencyError):
            g.topological_sort()


class TestFileConflictDetection:
    def test_no_conflict(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.claim_file("a", "main.py")
        g.claim_file("b", "routes.py")
        assert g.check_file_conflicts() == []

    def test_file_conflict_detected(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.claim_file("a", "main.py")
        g.claim_file("b", "main.py")
        conflicts = g.check_file_conflicts()
        assert len(conflicts) == 1
        assert "main.py" in str(conflicts[0])

    def test_same_directory_allowed(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.claim_file("a", "adapters/auth.py")
        g.claim_file("b", "adapters/admin.py")
        assert g.check_file_conflicts() == []
