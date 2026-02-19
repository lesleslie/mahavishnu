"""Tests for Dependency Visualization Module.

Tests cover:
- ASCII tree rendering
- Chain rendering
- Summary output
- Blocked task display
- Color coding
"""

from __future__ import annotations

import pytest

from mahavishnu.core.dependency_graph import DependencyGraph, DependencyStatus, DependencyType
from mahavishnu.core.dependency_visualization import (
    ColorCode,
    DependencyVisualizer,
    visualize_dependencies,
)


class TestColorCode:
    """Test color codes."""

    def test_color_codes_exist(self) -> None:
        """Test that all color codes are defined."""
        assert ColorCode.RESET.value
        assert ColorCode.RED.value
        assert ColorCode.GREEN.value
        assert ColorCode.YELLOW.value
        assert ColorCode.BLUE.value


class TestDependencyVisualizer:
    """Test dependency visualizer."""

    @pytest.fixture
    def graph(self) -> DependencyGraph:
        """Create sample dependency graph."""
        graph = DependencyGraph()
        graph.add_task("task-1", {"title": "First task"})
        graph.add_task("task-2", {"title": "Second task"})
        graph.add_task("task-3", {"title": "Third task"})
        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-2", "task-3")
        return graph

    @pytest.fixture
    def visualizer(self) -> DependencyVisualizer:
        """Create visualizer with colors enabled."""
        return DependencyVisualizer(use_colors=True)

    @pytest.fixture
    def plain_visualizer(self) -> DependencyVisualizer:
        """Create visualizer without colors."""
        return DependencyVisualizer(use_colors=False)

    def test_render_tree(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test tree rendering."""
        result = visualizer.render_tree(graph, "task-3")

        assert "task-3" in result
        assert "task-2" in result
        assert "task-1" in result

    def test_render_tree_max_depth(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test tree rendering with depth limit."""
        result = visualizer.render_tree(graph, "task-3", max_depth=1)

        # Should include task-3 and task-2, but not task-1
        assert "task-3" in result
        assert "task-2" in result

    def test_render_tree_shows_titles(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test that tree shows task titles."""
        result = visualizer.render_tree(graph, "task-3")

        assert "First task" in result
        assert "Second task" in result

    def test_render_tree_no_colors(self, plain_visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test tree rendering without colors."""
        result = plain_visualizer.render_tree(graph, "task-3")

        # Should not contain ANSI codes
        assert "\033[" not in result
        assert "task-3" in result

    def test_render_chain_dependencies(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test chain rendering for dependencies."""
        result = visualizer.render_chain(graph, "task-3", direction="dependencies")

        assert "task-3" in result
        assert "task-2" in result
        assert "task-1" in result

    def test_render_chain_dependents(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test chain rendering for dependents."""
        result = visualizer.render_chain(graph, "task-1", direction="dependents")

        assert "task-1" in result
        assert "task-2" in result
        assert "task-3" in result

    def test_render_chain_max_length(self, visualizer: DependencyVisualizer) -> None:
        """Test chain rendering with max length."""
        # Create longer chain
        graph = DependencyGraph()
        for i in range(10):
            graph.add_task(f"task-{i}")
            if i > 0:
                graph.add_dependency(f"task-{i-1}", f"task-{i}")

        result = visualizer.render_chain(graph, "task-9", max_length=5)

        # Should be truncated
        parts = result.split("→")
        assert len(parts) <= 5

    def test_render_summary(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test summary rendering."""
        result = visualizer.render_summary(graph)

        assert "Dependency Graph Summary" in result
        assert "Total Tasks: 3" in result
        assert "Total Dependencies: 2" in result

    def test_render_summary_blocked(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test summary with blocked tasks."""
        result = visualizer.render_summary(graph)

        assert "Blocked Tasks:" in result or "blocked" in result.lower()

    def test_render_summary_ready(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test summary with ready tasks."""
        result = visualizer.render_summary(graph)

        assert "Ready Tasks:" in result or "ready" in result.lower()

    def test_render_blocked_tree(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test blocked task tree rendering."""
        result = visualizer.render_blocked_tree(graph)

        # task-3 is blocked by task-2
        assert "task-3" in result

    def test_render_blocked_tree_empty(self, visualizer: DependencyVisualizer) -> None:
        """Test blocked tree with no blocked tasks."""
        graph = DependencyGraph()
        graph.add_task("task-1")

        result = visualizer.render_blocked_tree(graph)

        assert "No blocked tasks" in result

    def test_render_dependency_matrix(self, visualizer: DependencyVisualizer, graph: DependencyGraph) -> None:
        """Test matrix rendering."""
        result = visualizer.render_dependency_matrix(graph)

        # Should contain task IDs
        assert "task-1" in result
        assert "task-2" in result
        assert "task-3" in result

    def test_render_dependency_matrix_empty(self, visualizer: DependencyVisualizer) -> None:
        """Test matrix with empty graph."""
        graph = DependencyGraph()

        result = visualizer.render_dependency_matrix(graph)

        assert "Empty graph" in result

    def test_colorize_with_colors(self, visualizer: DependencyVisualizer) -> None:
        """Test colorize with colors enabled."""
        result = visualizer._colorize("test", ColorCode.RED)

        assert "\033[91m" in result
        assert "test" in result
        assert "\033[0m" in result

    def test_colorize_without_colors(self, plain_visualizer: DependencyVisualizer) -> None:
        """Test colorize with colors disabled."""
        result = plain_visualizer._colorize("test", ColorCode.RED)

        assert "\033[" not in result
        assert result == "test"


class TestVisualizeDependencies:
    """Test convenience function."""

    @pytest.fixture
    def graph(self) -> DependencyGraph:
        """Create sample graph."""
        graph = DependencyGraph()
        graph.add_task("task-1", {"title": "First"})
        graph.add_task("task-2", {"title": "Second"})
        graph.add_dependency("task-1", "task-2")
        return graph

    def test_tree_format(self, graph: DependencyGraph) -> None:
        """Test tree format."""
        result = visualize_dependencies(graph, "task-2", format="tree")

        assert "task-2" in result

    def test_chain_format(self, graph: DependencyGraph) -> None:
        """Test chain format."""
        result = visualize_dependencies(graph, "task-2", format="chain")

        assert "task-2" in result

    def test_summary_format(self, graph: DependencyGraph) -> None:
        """Test summary format."""
        result = visualize_dependencies(graph, format="summary")

        assert "Summary" in result

    def test_blocked_format(self, graph: DependencyGraph) -> None:
        """Test blocked format."""
        result = visualize_dependencies(graph, format="blocked")

        assert "task-2" in result  # task-2 is blocked

    def test_default_format(self, graph: DependencyGraph) -> None:
        """Test default format (summary)."""
        result = visualize_dependencies(graph, format="unknown")

        assert "Summary" in result

    def test_empty_graph(self) -> None:
        """Test with empty graph."""
        graph = DependencyGraph()

        result = visualize_dependencies(graph, format="tree")

        assert "Empty" in result or result == ""

    def test_tree_without_task_id(self, graph: DependencyGraph) -> None:
        """Test tree format without specifying task ID."""
        result = visualize_dependencies(graph, format="tree")

        # Should render from root task
        assert "task-1" in result


class TestComplexScenarios:
    """Test complex visualization scenarios."""

    @pytest.fixture
    def complex_graph(self) -> DependencyGraph:
        """Create complex dependency graph."""
        graph = DependencyGraph()

        # Diamond dependency pattern
        #     task-1
        #    /      \
        # task-2  task-3
        #    \      /
        #     task-4

        graph.add_task("task-1", {"title": "Root"})
        graph.add_task("task-2", {"title": "Left branch"})
        graph.add_task("task-3", {"title": "Right branch"})
        graph.add_task("task-4", {"title": "Leaf"})

        graph.add_dependency("task-1", "task-2")
        graph.add_dependency("task-1", "task-3")
        graph.add_dependency("task-2", "task-4")
        graph.add_dependency("task-3", "task-4")

        return graph

    def test_diamond_tree(self, complex_graph: DependencyGraph) -> None:
        """Test tree with diamond dependency."""
        viz = DependencyVisualizer(use_colors=False)
        result = viz.render_tree(complex_graph, "task-4")

        assert "task-4" in result
        assert "task-2" in result
        assert "task-3" in result

    def test_diamond_summary(self, complex_graph: DependencyGraph) -> None:
        """Test summary with diamond dependency."""
        viz = DependencyVisualizer(use_colors=False)
        result = viz.render_summary(complex_graph)

        assert "Total Tasks: 4" in result
        assert "Total Dependencies: 4" in result

    def test_matrix_with_diamond(self, complex_graph: DependencyGraph) -> None:
        """Test matrix with diamond pattern."""
        viz = DependencyVisualizer(use_colors=False)
        result = viz.render_dependency_matrix(complex_graph)

        # Should have 4x4 grid
        lines = result.split("\n")
        assert len(lines) >= 5  # Header + 4 rows


class TestStatusIndicators:
    """Test status indicators in visualizations."""

    def test_satisfied_status(self) -> None:
        """Test showing satisfied status."""
        graph = DependencyGraph()
        graph.add_task("task-1")
        graph.add_task("task-2")
        graph.add_dependency("task-1", "task-2")

        # Mark as satisfied
        graph.update_edge_status("task-1", "task-2", DependencyStatus.SATISFIED)

        viz = DependencyVisualizer(use_colors=True)
        result = viz.render_tree(graph, "task-2")

        assert "task-2" in result

    def test_different_dependency_types(self) -> None:
        """Test showing different dependency types."""
        graph = DependencyGraph()
        graph.add_task("task-1")
        graph.add_task("task-2")
        graph.add_task("task-3")
        graph.add_task("task-4")

        graph.add_dependency("task-1", "task-2", dependency_type=DependencyType.BLOCKS)
        graph.add_dependency("task-1", "task-3", dependency_type=DependencyType.REQUIRES)
        graph.add_dependency("task-1", "task-4", dependency_type=DependencyType.SUBTASK)

        viz = DependencyVisualizer(use_colors=False)
        result = viz.render_tree(graph, "task-4", show_type=True)

        assert "task-4" in result


class TestDepthCalculation:
    """Test depth visualization."""

    def test_depth_distribution(self) -> None:
        """Test depth distribution in summary."""
        graph = DependencyGraph()

        # Create chain
        for i in range(5):
            graph.add_task(f"task-{i}")
            if i > 0:
                graph.add_dependency(f"task-{i-1}", f"task-{i}")

        viz = DependencyVisualizer(use_colors=False)
        result = viz.render_summary(graph)

        assert "Depth Distribution" in result
        # task-4 has depth 4, task-3 has depth 3, etc.
        assert "Depth 4" in result or "depth: 4" in result.lower()

    def test_critical_path(self) -> None:
        """Test critical path display."""
        graph = DependencyGraph()

        # Create longest chain
        for i in range(4):
            graph.add_task(f"task-{i}")
            if i > 0:
                graph.add_dependency(f"task-{i-1}", f"task-{i}")

        # Add shorter chain
        graph.add_task("task-a")
        graph.add_task("task-b")
        graph.add_dependency("task-a", "task-b")

        viz = DependencyVisualizer(use_colors=False)
        result = viz.render_summary(graph)

        assert "Critical Path" in result
