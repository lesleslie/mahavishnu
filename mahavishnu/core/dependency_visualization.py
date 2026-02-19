"""Dependency Visualization Module for Mahavishnu.

Provides visualization utilities for dependency graphs:
- ASCII tree rendering
- Dependency chain display
- Status color coding
- Depth visualization
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from mahavishnu.core.dependency_graph import (
    DependencyGraph,
    DependencyStatus,
    DependencyType,
)

logger = logging.getLogger(__name__)


class ColorCode(str, Enum):
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    RED = "\033[91m"  # Failed/blocked
    GREEN = "\033[92m"  # Satisfied/ready
    YELLOW = "\033[93m"  # Pending/warning
    BLUE = "\033[94m"  # Info
    MAGENTA = "\033[95m"  # Subtask
    CYAN = "\033[96m"  # Related
    DIM = "\033[2m"  # Dimmed
    BOLD = "\033[1m"


class DependencyVisualizer:
    """Visualizes dependency graphs in terminal."""

    # Symbols for tree rendering
    SYMBOLS = {
        "branch": "├── ",
        "last_branch": "└── ",
        "vertical": "│   ",
        "empty": "    ",
        "arrow": "→ ",
        "bullet": "• ",
    }

    # Status indicators
    STATUS_ICONS = {
        DependencyStatus.PENDING: "⏳",
        DependencyStatus.SATISFIED: "✓",
        DependencyStatus.FAILED: "✗",
        DependencyStatus.CANCELLED: "⊘",
    }

    # Type indicators
    TYPE_ICONS = {
        DependencyType.BLOCKS: "🚫",
        DependencyType.REQUIRES: "📦",
        DependencyType.RELATED: "🔗",
        DependencyType.SUBTASK: "📎",
    }

    def __init__(self, use_colors: bool = True) -> None:
        """Initialize visualizer.

        Args:
            use_colors: Whether to use ANSI colors in output
        """
        self.use_colors = use_colors

    def render_tree(
        self,
        graph: DependencyGraph,
        task_id: str,
        max_depth: int = 5,
        show_status: bool = True,
        show_type: bool = True,
    ) -> str:
        """Render dependency tree as ASCII art.

        Args:
            graph: Dependency graph to visualize
            task_id: Root task to start from
            max_depth: Maximum depth to render
            show_status: Show status icons
            show_type: Show dependency type icons

        Returns:
            ASCII tree string
        """
        lines: list[str] = []
        visited: set[str] = set()

        def render_node(
            tid: str,
            prefix: str,
            is_last: bool,
            depth: int,
        ) -> None:
            if depth > max_depth:
                return

            # Cycle detection
            if tid in visited:
                cycle_indicator = self._colorize("↩ (cycle)", ColorCode.RED)
                lines.append(f"{prefix}{self.SYMBOLS['last_branch']}{cycle_indicator}")
                return

            visited.add(tid)

            # Get task info
            metadata = graph._task_metadata.get(tid, {})
            title = metadata.get("title", tid)

            # Build node line
            node_parts = []

            # Add status icon
            if show_status:
                # Check if blocked
                is_blocked = graph.is_blocked(tid)
                if is_blocked:
                    node_parts.append(self._colorize("⏳", ColorCode.YELLOW))
                else:
                    node_parts.append(self._colorize("✓", ColorCode.GREEN))

            # Add task ID/title
            title_str = f"{tid}: {title}" if title != tid else tid
            if graph.is_blocked(tid):
                node_parts.append(self._colorize(title_str, ColorCode.YELLOW))
            else:
                node_parts.append(self._colorize(title_str, ColorCode.GREEN))

            # Add depth indicator for leaf nodes
            deps = graph.get_dependencies(tid)
            if not deps:
                depth_str = self._colorize(f" (depth: {depth})", ColorCode.DIM)
                node_parts.append(depth_str)

            # Render node
            if depth == 0:
                lines.append(" ".join(node_parts))
            else:
                connector = self.SYMBOLS["last_branch"] if is_last else self.SYMBOLS["branch"]
                lines.append(f"{prefix}{connector}{' '.join(node_parts)}")

            # Render dependencies
            if deps and depth < max_depth:
                new_prefix = prefix + (self.SYMBOLS["empty"] if is_last else self.SYMBOLS["vertical"])

                for i, dep_id in enumerate(sorted(deps)):
                    is_last_dep = i == len(deps) - 1

                    # Add dependency type indicator
                    if show_type:
                        edge = graph.get_edge(dep_id, tid)
                        if edge:
                            type_icon = self.TYPE_ICONS.get(edge.dependency_type, "")
                            dep_prefix = f"{new_prefix}{type_icon} "
                        else:
                            dep_prefix = new_prefix
                    else:
                        dep_prefix = new_prefix

                    render_node(dep_id, new_prefix, is_last_dep, depth + 1)

        render_node(task_id, "", True, 0)
        return "\n".join(lines)

    def render_chain(
        self,
        graph: DependencyGraph,
        task_id: str,
        direction: str = "dependencies",
        max_length: int = 10,
    ) -> str:
        """Render a dependency chain as a linear path.

        Args:
            graph: Dependency graph
            task_id: Starting task
            direction: 'dependencies' or 'dependents'
            max_length: Maximum chain length

        Returns:
            ASCII chain string
        """
        visited: set[str] = set()
        chain: list[str] = []

        def get_next(tid: str) -> list[str]:
            if direction == "dependencies":
                return graph.get_dependencies(tid)
            else:
                return graph.get_dependents(tid)

        current = task_id
        while current and current not in visited and len(chain) < max_length:
            visited.add(current)
            metadata = graph._task_metadata.get(current, {})
            title = metadata.get("title", current)

            # Format node
            is_blocked = graph.is_blocked(current)
            node_str = f"{current}"
            if title and title != current:
                node_str += f": {title[:30]}"

            if is_blocked:
                node_str = self._colorize(node_str, ColorCode.YELLOW)
            else:
                node_str = self._colorize(node_str, ColorCode.GREEN)

            chain.append(node_str)

            # Get next
            next_tasks = get_next(current)
            current = next_tasks[0] if next_tasks else ""

        # Join with arrows
        arrow = self._colorize(" → ", ColorCode.DIM)
        return arrow.join(chain)

    def render_summary(self, graph: DependencyGraph) -> str:
        """Render a summary of the dependency graph.

        Args:
            graph: Dependency graph

        Returns:
            Summary string
        """
        lines: list[str] = []

        # Header
        lines.append(self._colorize("Dependency Graph Summary", ColorCode.BOLD))
        lines.append("")

        # Stats
        total_tasks = graph.get_task_count()
        total_edges = graph.get_edge_count()
        blocked = graph.get_blocked_tasks()
        ready = graph.get_ready_tasks()

        stats = [
            f"Total Tasks: {total_tasks}",
            f"Total Dependencies: {total_edges}",
            f"Ready Tasks: {self._colorize(str(len(ready)), ColorCode.GREEN)}",
            f"Blocked Tasks: {self._colorize(str(len(blocked)), ColorCode.YELLOW)}",
        ]

        lines.append("  " + "  |  ".join(stats))
        lines.append("")

        # Check for cycles
        if graph.has_cycle():
            lines.append(self._colorize("⚠ Cycles detected!", ColorCode.RED))
            cycles = graph.detect_cycles()
            for i, cycle in enumerate(cycles[:3]):  # Show first 3 cycles
                cycle_str = " → ".join(cycle[:5])  # Limit length
                if len(cycle) > 5:
                    cycle_str += "..."
                lines.append(f"  Cycle {i + 1}: {cycle_str}")
            lines.append("")

        # Show depth distribution
        depths: dict[int, int] = {}
        for tid in graph:
            depth = graph.get_dependency_depth(tid)
            depths[depth] = depths.get(depth, 0) + 1

        if depths:
            lines.append("Depth Distribution:")
            for depth in sorted(depths.keys()):
                count = depths[depth]
                bar = "█" * min(count, 20)
                lines.append(f"  Depth {depth}: {bar} ({count})")
            lines.append("")

        # Show critical path (longest dependency chain)
        max_depth = -1
        deepest_task = None
        for tid in graph:
            depth = graph.get_dependency_depth(tid)
            if depth > max_depth:
                max_depth = depth
                deepest_task = tid

        if deepest_task:
            lines.append(f"Critical Path (depth {max_depth}):")
            chain = self.render_chain(graph, deepest_task, "dependencies")
            lines.append(f"  {chain}")

        return "\n".join(lines)

    def render_blocked_tree(self, graph: DependencyGraph) -> str:
        """Render tree showing only blocked tasks and their blockers.

        Args:
            graph: Dependency graph

        Returns:
            ASCII tree of blocked tasks
        """
        blocked = graph.get_blocked_tasks()

        if not blocked:
            return self._colorize("No blocked tasks!", ColorCode.GREEN)

        lines: list[str] = []
        lines.append(self._colorize("Blocked Tasks:", ColorCode.YELLOW))
        lines.append("")

        for task_id in sorted(blocked):
            blocking = graph.get_blocking_tasks(task_id)
            metadata = graph._task_metadata.get(task_id, {})
            title = metadata.get("title", task_id)

            # Task line
            task_str = self._colorize(f"⏳ {task_id}: {title}", ColorCode.YELLOW)
            lines.append(f"  {task_str}")

            # Blocking tasks
            for blocker_id in blocking:
                blocker_meta = graph._task_metadata.get(blocker_id, {})
                blocker_title = blocker_meta.get("title", blocker_id)
                edge = graph.get_edge(blocker_id, task_id)

                # Status of blocking task
                blocker_str = f"{blocker_id}: {blocker_title}"
                if edge and edge.status == DependencyStatus.FAILED:
                    blocker_str = self._colorize(f"✗ {blocker_str}", ColorCode.RED)
                else:
                    blocker_str = self._colorize(f"⏳ {blocker_str}", ColorCode.YELLOW)

                lines.append(f"    {self.SYMBOLS['arrow']}{blocker_str}")

            lines.append("")

        return "\n".join(lines)

    def render_dependency_matrix(self, graph: DependencyGraph) -> str:
        """Render a matrix view of dependencies.

        Args:
            graph: Dependency graph

        Returns:
            ASCII matrix string
        """
        tasks = sorted(graph.get_all_tasks())
        if not tasks:
            return "Empty graph"

        # Calculate column widths
        task_width = max(len(t) for t in tasks) + 2
        cell_width = 3

        lines: list[str] = []

        # Header
        header = " " * task_width
        for task in tasks:
            # Truncate task ID for header
            short_id = task[:cell_width].ljust(cell_width)
            header += short_id
        lines.append(self._colorize(header, ColorCode.DIM))

        # Rows
        for row_task in tasks:
            row = row_task.ljust(task_width)

            for col_task in tasks:
                if row_task == col_task:
                    cell = self._colorize(" · ", ColorCode.DIM)
                elif graph.get_edge(col_task, row_task):
                    edge = graph.get_edge(col_task, row_task)
                    if edge.status == DependencyStatus.SATISFIED:
                        cell = self._colorize(" ✓ ", ColorCode.GREEN)
                    elif edge.status == DependencyStatus.FAILED:
                        cell = self._colorize(" ✗ ", ColorCode.RED)
                    else:
                        cell = self._colorize(" → ", ColorCode.BLUE)
                else:
                    cell = "   "
                row += cell

            lines.append(row)

        return "\n".join(lines)

    def _colorize(self, text: str, color: ColorCode) -> str:
        """Apply color to text if colors are enabled.

        Args:
            text: Text to colorize
            color: Color to apply

        Returns:
            Colorized text (or plain text if colors disabled)
        """
        if not self.use_colors:
            return text

        return f"{color.value}{text}{ColorCode.RESET.value}"


def visualize_dependencies(
    graph: DependencyGraph,
    task_id: str | None = None,
    format: str = "tree",
    max_depth: int = 5,
) -> str:
    """Convenience function to visualize dependencies.

    Args:
        graph: Dependency graph
        task_id: Optional root task (for tree format)
        format: Output format ('tree', 'chain', 'summary', 'blocked')
        max_depth: Maximum depth for tree

    Returns:
        Visualization string
    """
    viz = DependencyVisualizer()

    if format == "tree":
        if not task_id:
            # Find root tasks (no dependents)
            roots = [t for t in graph if not graph.get_dependents(t)]
            if not roots:
                roots = list(graph)[:1]  # Default to first task
            if roots:
                return "\n\n".join(
                    viz.render_tree(graph, r, max_depth) for r in roots[:3]
                )
            return "Empty graph"
        return viz.render_tree(graph, task_id, max_depth)

    elif format == "chain":
        if not task_id:
            task_id = next(iter(graph), None)
        if task_id:
            return viz.render_chain(graph, task_id)
        return "Empty graph"

    elif format == "summary":
        return viz.render_summary(graph)

    elif format == "blocked":
        return viz.render_blocked_tree(graph)

    else:
        return viz.render_summary(graph)
