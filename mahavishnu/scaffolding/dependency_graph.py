"""Pattern dependency graph with topological sort and conflict detection."""

from __future__ import annotations

from collections import defaultdict
import heapq


class CircularDependencyError(Exception):
    """Raised when a cycle is detected in pattern dependencies."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency: {' -> '.join(cycle)}")


class PatternDependencyGraph:
    """Directed graph for pattern dependencies with topological ordering.

    Provides:
    - Topological sort with alphabetical tie-breaking for deterministic output
    - File claim tracking to detect when two patterns generate the same file
    """

    def __init__(self) -> None:
        self._deps: dict[str, set[str]] = defaultdict(set)
        self._nodes: set[str] = set()
        self._file_claims: dict[str, list[str]] = defaultdict(list)

    def add(self, pattern_id: str) -> None:
        """Register a pattern node in the graph."""
        self._nodes.add(pattern_id)

    def add_edge(self, prerequisite: str, dependent: str) -> None:
        """Add a directed edge: prerequisite must come before dependent.

        Both nodes are implicitly added if not already present.
        """
        self._nodes.add(prerequisite)
        self._nodes.add(dependent)
        self._deps[dependent].add(prerequisite)

    def claim_file(self, pattern_id: str, file_path: str) -> None:
        """Register that a pattern will generate a specific file."""
        self._file_claims[file_path].append(pattern_id)

    def topological_sort(self) -> list[str]:
        """Return patterns in dependency order (prerequisites first).

        Uses Kahn's algorithm with a min-heap for alphabetical tie-breaking.
        Raises CircularDependencyError if a cycle is detected.
        """
        # in_degree[node] = number of prerequisites for node
        in_degree: dict[str, int] = {n: len(self._deps.get(n, set())) for n in self._nodes}
        # reverse[node] = list of nodes that depend on node
        reverse: dict[str, list[str]] = defaultdict(list)
        for dependent, prereqs in self._deps.items():
            for prereq in prereqs:
                reverse[prereq].append(dependent)

        # Initialize heap with nodes that have no prerequisites
        heap: list[str] = sorted(n for n in self._nodes if in_degree[n] == 0)
        heapq.heapify(heap)

        order: list[str] = []
        while heap:
            node = heapq.heappop(heap)
            order.append(node)
            for dependent in reverse.get(node, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    heapq.heappush(heap, dependent)

        if len(order) != len(self._nodes):
            raise CircularDependencyError(
                sorted(self._nodes - set(order))
            )

        return order

    def check_file_conflicts(self) -> list[tuple[str, str, str]]:
        """Detect files claimed by more than one pattern.

        Returns a list of (first_claimant, second_claimant, file_path) tuples.
        """
        conflicts: list[tuple[str, str, str]] = []
        for file_path, claimants in self._file_claims.items():
            unique_claimants = list(dict.fromkeys(claimants))
            if len(unique_claimants) > 1:
                conflicts.append((unique_claimants[0], unique_claimants[1], file_path))
        return conflicts
