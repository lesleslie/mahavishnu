"""Learning path discovery for skill relationships."""

from collections import deque

import networkx as nx

from .graph import SkillGraph


def find_learning_path(
    graph: SkillGraph, start_skill: str, end_skill: str, max_depth: int = 10
) -> list[str] | None:
    """
    Find shortest path between two skills using BFS.

    Args:
        graph: SkillGraph to search
        start_skill: Name of starting skill
        end_skill: Name of target skill
        max_depth: Maximum path length to search

    Returns:
        List of skill names in order, or None if no path found
    """
    if start_skill not in graph.skills or end_skill not in graph.skills:
        return None

    if start_skill == end_skill:
        return [start_skill]

    # BFS for shortest path
    queue = deque([(start_skill, [start_skill])])
    visited = {start_skill}

    while queue:
        current, path = queue.popleft()

        if len(path) > max_depth:
            continue

        # Get neighbors (outgoing edges)
        neighbors = list(graph.graph.successors(current))

        for neighbor in neighbors:
            if neighbor == end_skill:
                return path + [neighbor]

            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return None


def find_all_paths(
    graph: SkillGraph, start_skill: str, end_skill: str, max_paths: int = 10, max_depth: int = 10
) -> list[list[str]]:
    """
    Find all paths between two skills (up to max_paths).

    Args:
        graph: SkillGraph to search
        start_skill: Name of starting skill
        end_skill: Name of target skill
        max_paths: Maximum number of paths to return
        max_depth: Maximum path length to search

    Returns:
        List of paths (each path is a list of skill names)
    """
    if start_skill not in graph.skills or end_skill not in graph.skills:
        return []

    if start_skill == end_skill:
        return [[start_skill]]

    paths = []

    def dfs(current: str, path: list[str], visited: set[str]):
        nonlocal paths

        if len(paths) >= max_paths:
            return

        if len(path) > max_depth:
            return

        if current == end_skill:
            paths.append(path.copy())
            return

        visited.add(current)

        for neighbor in graph.graph.successors(current):
            if neighbor not in visited:
                dfs(neighbor, path + [neighbor], visited.copy())

    dfs(start_skill, [start_skill], set())
    return paths


def get_prerequisite_skills(graph: SkillGraph, skill_name: str) -> dict[str, list[str]]:
    """
    Get all prerequisites for a skill (transitive REQUIRED skills).

    Args:
        graph: SkillGraph to analyze
        skill_name: Name of skill to analyze

    Returns:
        Dictionary with 'direct' and 'transitive' prerequisite lists
    """
    if skill_name not in graph.skills:
        return {"direct": [], "transitive": []}

    skill = graph.skills[skill_name]
    direct_reqs = [
        r.name for r in skill.related_skills if r.relationship_type.upper() == "REQUIRED"
    ]

    # Find transitive prerequisites
    transitive = set()
    visited = set()

    def collect_transitive(skill_name: str):
        if skill_name in visited:
            return
        visited.add(skill_name)

        if skill_name not in graph.skills:
            return

        for related in graph.skills[skill_name].related_skills:
            if related.relationship_type.upper() == "REQUIRED":
                transitive.add(related.name)
                collect_transitive(related.name)

    collect_transitive(skill_name)

    # Remove direct prerequisites from transitive
    transitive -= set(direct_reqs)

    return {"direct": direct_reqs, "transitive": sorted(transitive)}


def suggest_learning_order(graph: SkillGraph, skill_names: list[str]) -> list[str]:
    """
    Suggest optimal learning order using topological sort.

    Args:
        graph: SkillGraph to analyze
        skill_names: List of skills to order

    Returns:
        Ordered list of skill names (prerequisites first)
    """
    # Filter to only skills that exist
    valid_skills = [s for s in skill_names if s in graph.skills]

    if not valid_skills:
        return []

    # Build subgraph with only specified skills
    subgraph = graph.graph.subgraph(valid_skills)

    # Topological sort using Kahn's algorithm
    in_degree = dict.fromkeys(valid_skills, 0)
    for node in valid_skills:
        in_degree[node] = subgraph.in_degree(node)

    queue = deque([node for node in valid_skills if in_degree[node] == 0])
    result = []

    while queue:
        node = queue.popleft()
        result.append(node)

        for neighbor in subgraph.successors(node):
            if neighbor in valid_skills:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

    # If not all nodes processed, there's a cycle
    if len(result) != len(valid_skills):
        # Return original order as fallback
        return valid_skills

    return result


def find_dependencies(graph: SkillGraph, skill_name: str) -> dict[str, list[str]]:
    """
    Find all skills that depend on the given skill.

    Args:
        graph: SkillGraph to analyze
        skill_name: Name of skill to analyze

    Returns:
        Dictionary with 'direct' and 'transitive' dependent lists
    """
    if skill_name not in graph.skills:
        return {"direct": [], "transitive": []}

    # Direct dependents (incoming edges)
    direct_dependents = list(graph.graph.predecessors(skill_name))

    # Transitive dependents
    transitive = set()

    for dependent in direct_dependents:
        # Find all nodes that can reach this dependent
        for node in graph.graph.nodes():
            if node != skill_name and node != dependent:
                try:
                    if nx.has_path(graph.graph, node, skill_name):
                        if dependent in nx.shortest_path(graph.graph, node, skill_name):
                            transitive.add(node)
                except nx.NetworkXError:
                    pass

    return {"direct": direct_dependents, "transitive": sorted(transitive)}
