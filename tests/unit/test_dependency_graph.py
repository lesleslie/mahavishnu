"""Tests for Dependency Graph Module.

Tests cover:
- Graph construction and manipulation
- Cycle detection
- Topological sort
- Dependency queries
- Transitive dependencies
"""

from __future__ import annotations

import pytest

from mahavishnu.core.dependency_graph import (
    CircularDependencyError,
    Dependency,
    DependencyEdge,
    DependencyError,
    DependencyGraph,
    DependencyStatus,
    DependencyType,
    create_dependency_graph,
)


class TestDependencyEdge:
    """Test dependency edge model."""

    def test_create_edge(self) -> None:
        """Test creating a dependency edge."""
        edge = DependencyEdge(
            dependency_id="task-1",
            dependent_id="task-2",
            dependency_type=DependencyType.BLOCKS,
        )

        assert edge.dependency_id == "task-1"
        assert edge.dependent_id == "task-2"
        assert edge.dependency_type == DependencyType.BLOCKS
        assert edge.status == DependencyStatus.PENDING

    def test_edge_to_dict(self) -> None:
        """Test edge serialization."""
        edge = DependencyEdge(
            dependency_id="task-1",
            dependent_id="task-2",
            metadata={"reason": "Testing"},
        )

        d = edge.to_dict()

        assert d["dependency_id"] == "task-1"
        assert d["dependent_id"] == "task-2"
        assert d["metadata"]["reason"] == "Testing"


class TestDependency:
    """Test Pydantic dependency model."""

    def test_create_dependency(self) -> None:
        """Test creating a dependency."""
        dep = Dependency(
            dependency_id="task-1",
            dependent_id="task-2",
        )

        assert dep.dependency_id == "task-1"
        assert dep.dependent_id == "task-2"
        assert dep.dependency_type == DependencyType.BLOCKS
        assert dep.status == DependencyStatus.PENDING

    def test_dependency_to_dict(self) -> None:
        """Test dependency serialization."""
        dep = Dependency(
            id="dep-1",
            dependency_id="task-1",
            dependent_id="task-2",
            dependency_type=DependencyType.REQUIRES,
        )

        d = dep.to_dict()

        assert d["id"] == "dep-1"
        assert d["dependency_type"] == "requires"


class TestDependencyGraph:
    """Test dependency graph operations."""

    @pytest.fixture
    def graph(self) -> DependencyGraph:
        """Create empty dependency graph."""
        return DependencyGraph()

    def test_empty_graph(self, graph: DependencyGraph) -> None:
        """Test empty graph properties."""
        assert len(graph) == 0
        assert graph.get_task_count() == 0
        assert graph.get_edge_count() == 0

    def test_add_task(self, graph: DependencyGraph) -> None:
        """Test adding tasks."""
        graph.add_task("task-1", {"title": "First task"})
        graph.add_task("task-2")

        assert len(graph) == 2
        assert "task-1" in graph
        assert "task-2" in graph

    def test_remove_task(self, graph: DependencyGraph) -> None:
        """Test removing tasks."""
        graph.add_task("task-1")
        graph.add_task("task-2")
        graph.add_dependency("task-1", "task-2")

        affected = graph.remove_task("task-1")

        assert len(graph) == 1
        assert "task-1" not in graph
        assert "task-2" in affected
        assert graph.get_dependencies("task-2") == []

    def test_add_dependency(self, graph: DependencyGraph) -> None:
        """Test adding dependencies."""
        graph.add_task("task-1")
        graph.add_task("task-2")

        edge = graph.add_dependency("task-1", "task-2")

        assert edge.dependency_id == "task-1"
        assert edge.dependent_id == "task-2"
        assert graph.get_dependencies("task-2") == ["task-1"]
        assert graph.get_dependents("task-1") == ["task-2"]

    def test_add_dependency_creates_tasks(self, graph: DependencyGraph) -> None:
        """Test that adding dependency creates tasks if needed."""
        graph.add_dependency("task-1", "task-2")

        assert "task-1" in graph
        assert "task-2" in graph
        assert graph.get_dependencies("task-2") == ["task-1"]

    def test_remove_dependency(self, graph: DependencyGraph) -> None:
        """Test removing dependencies."""
        graph.add_dependency("task-1", "task-2")

        result = graph.remove_dependency("task-1", "task-2")

        assert result is True
        assert graph.get_dependencies("task-2") == []

    def test_remove_nonexistent_dependency(self, graph: DependencyGraph) -> None:
        """Test removing dependency that doesn't exist."""
        result = graph.remove_dependency("task-1", "task-2")
        assert result is False

    def test_duplicate_dependency_error(self, graph: DependencyGraph) -> None:
        """Test that duplicate dependencies raise error."""
        graph.add_dependency("task-1", "task-2")

        with pytest.raises(DependencyError) as exc_info:
            graph.add_dependency("task-1", "task-2")

        assert "already exists" in str(exc_info.value)

    def test_is_blocked(self, graph: DependencyGraph) -> None:
        """Test blocking status."""
        graph.add_dependency("task-1", "task-2")

        assert graph.is_blocked("task-2") is True
        assert graph.is_blocked("task-1") is False

    def test_get_blocking_tasks(self, graph: DependencyGraph) -> None:
        """Test getting blocking tasks."""
        graph.add_dependency("task-1", "task-3")
        graph.add_dependency("task-2", "task-3")

        blocking = graph.get_blocking_tasks("task-3")

        assert len(blocking) == 2
        assert "task-1" in blocking
        assert "task-2" in blocking

    def test_update_edge_status(self, graph: DependencyGraph) -> None:
        """Test updating edge status."""
        graph.add_dependency("task-1", "task-2")

        result = graph.update_edge_status(
            "task-1", "task-2", DependencyStatus.SATISFIED
        )

        assert result is True
        edge = graph.get_edge("task-1", "task-2")
        assert edge.status == DependencyStatus.SATISFIED
        assert graph.is_blocked("task-2") is False

    def test_get_ready_tasks(self, graph: DependencyGraph) -> None:
        """Test getting ready tasks."""
        graph.add_task("task-1")
        graph.add_task("task-2")
        graph.add_dependency("task-1", "task-3")

        ready = graph.get_ready_tasks()

        assert "task-1" in ready
        assert "task-2" in ready
        assert "task-3" not in ready

    def test_get_blocked_tasks(self, graph: DependencyGraph) -> None:
        """Test getting blocked tasks."""
        graph.add_task("task-1")
        graph.add_task("task-2")
        graph.add_dependency("task-1", "task-3")

        blocked = graph.get_blocked_tasks()

        assert "task-3" in blocked
        assert "task-1" not in blocked


class TestCycleDetection:
    """Test cycle detection algorithms."""

    @pytest.fixture
    def graph(self) -> DependencyGraph:
        """Create empty graph."""
        return DependencyGraph()

    def test_no_cycle(self, graph: DependencyGraph) -> None:
        """Test graph without cycles."""
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-2", "task-3")

        assert graph.has_cycle() is False
        assert graph.detect_cycles() == []

    def test_simple_cycle(self, graph: DependencyGraph) -> None:
        """Test detection of simple cycle."""
        graph.add_dependency("task-1", "task-2", validate=False)
        graph.add_dependency("task-2", "task-1", validate=False)

        assert graph.has_cycle() is True
        cycles = graph.detect_cycles()
        assert len(cycles) > 0
        assert "task-1" in cycles[0]
        assert "task-2" in cycles[0]

    def test_prevent_cycle_on_add(self, graph: DependencyGraph) -> None:
        """Test that adding edge that creates cycle is prevented."""
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-2", "task-3")

        with pytest.raises(CircularDependencyError) as exc_info:
            graph.add_dependency("task-3", "task-1")

        assert "task-1" in exc_info.value.cycle
        assert "task-3" in exc_info.value.cycle

    def test_longer_cycle(self, graph: DependencyGraph) -> None:
        """Test detection of longer cycle."""
        graph.add_dependency("task-1", "task-2", validate=False)
        graph.add_dependency("task-2", "task-3", validate=False)
        graph.add_dependency("task-3", "task-1", validate=False)

        assert graph.has_cycle() is True
        cycles = graph.detect_cycles()
        assert len(cycles) > 0

    def test_multiple_cycles(self, graph: DependencyGraph) -> None:
        """Test detection of multiple cycles."""
        # First cycle
        graph.add_dependency("task-1", "task-2", validate=False)
        graph.add_dependency("task-2", "task-1", validate=False)

        # Second cycle (disconnected)
        graph.add_dependency("task-3", "task-4", validate=False)
        graph.add_dependency("task-4", "task-3", validate=False)

        cycles = graph.detect_cycles()
        assert len(cycles) >= 2


class TestTopologicalSort:
    """Test topological sort."""

    @pytest.fixture
    def graph(self) -> DependencyGraph:
        """Create empty graph."""
        return DependencyGraph()

    def test_simple_sort(self, graph: DependencyGraph) -> None:
        """Test simple topological sort."""
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-2", "task-3")

        order = graph.topological_sort()

        assert order.index("task-1") < order.index("task-2")
        assert order.index("task-2") < order.index("task-3")

    def test_complex_sort(self, graph: DependencyGraph) -> None:
        """Test more complex topological sort."""
        # task-1 -> task-2 -> task-4
        # task-1 -> task-3 -> task-4
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-1", "task-3")
        graph.add_dependency("task-2", "task-4")
        graph.add_dependency("task-3", "task-4")

        order = graph.topological_sort()

        assert order.index("task-1") < order.index("task-2")
        assert order.index("task-1") < order.index("task-3")
        assert order.index("task-2") < order.index("task-4")
        assert order.index("task-3") < order.index("task-4")

    def test_sort_with_cycle_raises(self, graph: DependencyGraph) -> None:
        """Test that sort with cycle raises error."""
        graph.add_dependency("task-1", "task-2", validate=False)
        graph.add_dependency("task-2", "task-1", validate=False)

        with pytest.raises(CircularDependencyError):
            graph.topological_sort()


class TestTransitiveDependencies:
    """Test transitive dependency operations."""

    @pytest.fixture
    def graph(self) -> DependencyGraph:
        """Create graph with chain."""
        graph = DependencyGraph()
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-2", "task-3")
        graph.add_dependency("task-3", "task-4")
        return graph

    def test_get_transitive_dependencies(self, graph: DependencyGraph) -> None:
        """Test getting all transitive dependencies."""
        deps = graph.get_transitive_dependencies("task-4")

        assert deps == {"task-1", "task-2", "task-3"}

    def test_get_transitive_dependents(self, graph: DependencyGraph) -> None:
        """Test getting all transitive dependents."""
        deps = graph.get_transitive_dependents("task-1")

        assert deps == {"task-2", "task-3", "task-4"}

    def test_no_transitive_deps(self, graph: DependencyGraph) -> None:
        """Test transitive deps with no dependencies."""
        deps = graph.get_transitive_dependencies("task-1")

        assert deps == set()


class TestDependencyDepth:
    """Test dependency depth calculation."""

    @pytest.fixture
    def graph(self) -> DependencyGraph:
        """Create graph with varying depths."""
        graph = DependencyGraph()
        graph.add_dependency("task-1", "task-3")
        graph.add_dependency("task-2", "task-3")
        graph.add_dependency("task-3", "task-4")
        return graph

    def test_depth_no_deps(self, graph: DependencyGraph) -> None:
        """Test depth with no dependencies."""
        assert graph.get_dependency_depth("task-1") == 0
        assert graph.get_dependency_depth("task-2") == 0

    def test_depth_with_deps(self, graph: DependencyGraph) -> None:
        """Test depth with dependencies."""
        assert graph.get_dependency_depth("task-3") == 1
        assert graph.get_dependency_depth("task-4") == 2


class TestDependencyTree:
    """Test dependency tree generation."""

    def test_simple_tree(self) -> None:
        """Test simple dependency tree."""
        graph = DependencyGraph()
        graph.add_dependency("task-1", "task-3")
        graph.add_dependency("task-2", "task-3")

        tree = graph.get_dependency_tree("task-3")

        assert tree["id"] == "task-3"
        assert len(tree["dependencies"]) == 2
        dep_ids = {d["id"] for d in tree["dependencies"]}
        assert dep_ids == {"task-1", "task-2"}

    def test_nested_tree(self) -> None:
        """Test nested dependency tree."""
        graph = DependencyGraph()
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-2", "task-3")

        tree = graph.get_dependency_tree("task-3")

        assert tree["id"] == "task-3"
        assert tree["dependencies"][0]["id"] == "task-2"
        assert tree["dependencies"][0]["dependencies"][0]["id"] == "task-1"


class TestSerialization:
    """Test graph serialization."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        graph = DependencyGraph()
        graph.add_task("task-1", {"title": "First"})
        graph.add_task("task-2", {"title": "Second"})
        graph.add_dependency("task-1", "task-2")

        data = graph.to_dict()

        assert len(data["tasks"]) == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0]["dependency_id"] == "task-1"

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "tasks": [
                {"id": "task-1", "title": "First"},
                {"id": "task-2", "title": "Second"},
            ],
            "edges": [
                {
                    "dependency_id": "task-1",
                    "dependent_id": "task-2",
                    "dependency_type": "blocks",
                }
            ],
        }

        graph = DependencyGraph.from_dict(data)

        assert len(graph) == 2
        assert graph.get_dependencies("task-2") == ["task-1"]

    def test_roundtrip(self) -> None:
        """Test serialization roundtrip."""
        original = DependencyGraph()
        original.add_task("task-1", {"priority": "high"})
        original.add_dependency("task-1", "task-2")
        original.add_dependency("task-2", "task-3")

        data = original.to_dict()
        restored = DependencyGraph.from_dict(data)

        assert len(restored) == len(original)
        assert restored.get_dependencies("task-2") == ["task-1"]
        assert restored.get_dependencies("task-3") == ["task-2"]


class TestConvenienceFunction:
    """Test convenience function."""

    def test_create_dependency_graph(self) -> None:
        """Test creating graph via convenience function."""
        graph = create_dependency_graph()

        assert isinstance(graph, DependencyGraph)
        assert len(graph) == 0


class TestIteration:
    """Test iteration over graph."""

    def test_iter_tasks(self) -> None:
        """Test iterating over tasks."""
        graph = DependencyGraph()
        graph.add_task("task-1")
        graph.add_task("task-2")
        graph.add_task("task-3")

        task_ids = list(graph)

        assert len(task_ids) == 3
        assert "task-1" in task_ids
        assert "task-2" in task_ids
        assert "task-3" in task_ids


class TestClear:
    """Test clearing graph."""

    def test_clear_graph(self) -> None:
        """Test clearing the entire graph."""
        graph = DependencyGraph()
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-2", "task-3")

        graph.clear()

        assert len(graph) == 0
        assert graph.get_edge_count() == 0


class TestDependencyTypes:
    """Test different dependency types."""

    def test_blocks_type(self) -> None:
        """Test BLOCKS dependency type."""
        graph = DependencyGraph()
        edge = graph.add_dependency(
            "task-1", "task-2", dependency_type=DependencyType.BLOCKS
        )

        assert edge.dependency_type == DependencyType.BLOCKS

    def test_requires_type(self) -> None:
        """Test REQUIRES dependency type."""
        graph = DependencyGraph()
        edge = graph.add_dependency(
            "task-1", "task-2", dependency_type=DependencyType.REQUIRES
        )

        assert edge.dependency_type == DependencyType.REQUIRES

    def test_subtask_type(self) -> None:
        """Test SUBTASK dependency type."""
        graph = DependencyGraph()
        edge = graph.add_dependency(
            "task-1", "task-2", dependency_type=DependencyType.SUBTASK
        )

        assert edge.dependency_type == DependencyType.SUBTASK
