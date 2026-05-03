"""Analysis and visualization of skill graph properties."""

from .graph import SkillGraph


def analyze_connectivity(graph: SkillGraph) -> dict[str, any]:
    """
    Analyze overall graph connectivity.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Dictionary with connectivity metrics
    """
    return {
        "total_nodes": graph.graph.number_of_nodes(),
        "total_edges": graph.graph.number_of_edges(),
        "density": nx.density(graph.graph),
        "is_connected": nx.is_weakly_connected(graph.graph),
        "weakly_connected_components": nx.number_weakly_connected_components(graph.graph),
        "strongly_connected_components": nx.number_strongly_connected_components(graph.graph),
    }


def find_bridge_skills(graph: SkillGraph) -> list[tuple[str, str]]:
    """
    Find bridge edges (critical connections between skill groups).

    Args:
        graph: SkillGraph to analyze

    Returns:
        List of (source, target) tuples representing bridge edges
    """
    bridges = list(nx.bridges(nx.Graph(graph.graph.to_undirected())))
    return bridges


def find_central_topics(graph: SkillGraph, top_n: int = 10) -> list[tuple[str, float]]:
    """
    Find most central skills using betweenness centrality.

    Args:
        graph: SkillGraph to analyze
        top_n: Number of top skills to return

    Returns:
        List of (skill_name, centrality_score) tuples
    """
    centrality = nx.betweenness_centrality(graph.graph)
    sorted_centrality = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
    return sorted_centrality[:top_n]


def analyze_system_connections(graph: SkillGraph) -> dict[str, dict[str, int]]:
    """
    Analyze inter-system connections.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Nested dict: {source_system: {target_system: edge_count}}
    """
    connections: dict[str, dict[str, int]] = {}

    for source, target in graph.graph.edges():
        source_system = graph.skills[source].system
        target_system = graph.skills[target].system

        if source_system not in connections:
            connections[source_system] = {}

        if target_system not in connections[source_system]:
            connections[source_system][target_system] = 0

        connections[source_system][target_system] += 1

    return connections


def find_skill_clusters_by_keywords(graph: SkillGraph) -> dict[str, list[str]]:
    """
    Cluster skills by keyword similarity.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Dictionary mapping keywords to lists of related skills
    """
    keyword_clusters: dict[str, list[str]] = {}

    for skill_name, skill in graph.skills.items():
        for keyword in skill.keywords:
            if keyword not in keyword_clusters:
                keyword_clusters[keyword] = []
            keyword_clusters[keyword].append(skill_name)

    # Filter to only keywords with multiple skills
    return {k: v for k, v in keyword_clusters.items() if len(v) > 1}


def detect_cycles(graph: SkillGraph) -> list[list[str]]:
    """
    Detect circular dependencies in skill relationships.

    Args:
        graph: SkillGraph to analyze

    Returns:
        List of cycles (each cycle is a list of skill names)
    """
    try:
        cycles = list(nx.simple_cycles(graph.graph))
        return cycles
    except nx.NetworkXError:
        return []


def get_statistics_summary(graph: SkillGraph) -> str:
    """
    Get human-readable statistics summary.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Formatted summary string
    """
    stats = analyze_connectivity(graph)
    centrality = analyze_centrality(graph)
    orphans = find_orphan_skills(graph)
    clusters = detect_clusters(graph)

    lines = [
        "Skill Graph Statistics",
        "=" * 50,
        f"Total Skills: {stats['total_nodes']}",
        f"Total Relationships: {stats['total_edges']}",
        f"Graph Density: {stats['density']:.3f}",
        f"Connected: {stats['is_connected']}",
        "",
        "System Distribution:",
    ]

    for system, skills in sorted(clusters.items()):
        lines.append(f"  {system}: {len(skills)} skills")

    lines.extend(
        [
            "",
            f"Orphan Skills: {len(orphans)}",
            "",
            "Top 5 Most Central Skills (PageRank):",
        ]
    )

    # Convert to list of tuples for slicing
    centrality_list = list(centrality.items())
    for skill, score in centrality_list[:5]:
        lines.append(f"  {skill}: {score:.4f}")

    cycles = detect_cycles(graph)
    if cycles:
        lines.extend(
            [
                "",
                f"Circular Dependencies: {len(cycles)}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "No circular dependencies detected",
            ]
        )

    return "\n".join(lines)


def find_related_skills_by_similarity(
    graph: SkillGraph, skill_name: str, limit: int = 5
) -> list[tuple[str, float]]:
    """
    Find skills similar to a given skill based on keyword overlap.

    Args:
        graph: SkillGraph to analyze
        skill_name: Name of skill to find similar skills for
        limit: Maximum number of similar skills to return

    Returns:
        List of (skill_name, similarity_score) tuples
    """
    if skill_name not in graph.skills:
        return []

    target_skill = graph.skills[skill_name]
    target_keywords = set(target_skill.keywords)

    similarities = []

    for other_name, other_skill in graph.skills.items():
        if other_name == skill_name:
            continue

        other_keywords = set(other_skill.keywords)

        # Jaccard similarity
        intersection = len(target_keywords & other_keywords)
        union = len(target_keywords | other_keywords)

        if union > 0:
            similarity = intersection / union
            if similarity > 0:
                similarities.append((other_name, similarity))

    # Sort by similarity descending
    similarities.sort(key=lambda x: x[1], reverse=True)
    return similarities[:limit]


def get_skill_system_graph(graph: SkillGraph) -> dict[str, dict[str, int]]:
    """
    Build system-level graph showing connections between systems.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Nested dict: {source_system: {target_system: edge_count}}
    """
    return analyze_system_connections(graph)


def export_system_matrix(graph: SkillGraph) -> str:
    """
    Export system connection matrix as formatted text.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Formatted matrix string
    """
    connections = get_skill_system_graph(graph)
    systems = sorted(
        set(connections.keys()) | set(sys for subs in connections.values() for sys in subs.keys())
    )

    # Build matrix
    lines = ["System Connection Matrix"]
    lines.append(" " * 20 + " | " + " | ".join(systems))
    lines.append("-" * (20 + 3 + len(systems) * 15))

    for source in systems:
        row = [source.ljust(20)]
        for target in systems:
            count = connections.get(source, {}).get(target, 0)
            row.append(str(count).rjust(3))
        lines.append(" | ".join(row) + " |")

    return "\n".join(lines)


# Import at module level for use in functions
import networkx as nx

from .graph import analyze_centrality, detect_clusters, find_orphan_skills
