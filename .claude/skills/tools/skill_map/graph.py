"""Graph building for skill relationship visualization."""

from typing import Dict, List, Set, Optional
from dataclasses import dataclass, field
import networkx as nx

from skill_parser import SkillMetadata, RelatedSkill


@dataclass
class SkillGraph:
    """Directed graph of skill relationships."""
    graph: nx.DiGraph = field(default_factory=nx.DiGraph)
    skills: Dict[str, SkillMetadata] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure graph is initialized."""
        if not hasattr(self, 'graph') or self.graph is None:
            self.graph = nx.DiGraph()

    def add_skill(self, skill: SkillMetadata) -> None:
        """Add a skill node to the graph."""
        self.skills[skill.name] = skill
        self.graph.add_node(skill.name, **_skill_to_node_attributes(skill))

    def add_relationship(
        self,
        source: str,
        target: str,
        relationship_type: str
    ) -> None:
        """Add a relationship edge between skills."""
        self.graph.add_edge(source, target, relationship_type=relationship_type)


def _skill_to_node_attributes(skill: SkillMetadata) -> dict:
    """Convert skill metadata to node attributes for graph visualization."""
    return {
        "system": skill.system,
        "description": skill.description[:100] + "..." if len(skill.description) > 100 else skill.description,
        "keywords": ", ".join(skill.keywords[:5]),
        "has_examples": skill.has_examples,
        "word_count": skill.word_count,
        "related_count": len(skill.related_skills),
        "referenced_by_count": len(skill.referenced_by),
        "color": _get_system_color(skill.system),
    }


def _get_system_color(system: str) -> str:
    """Get color for system in visualizations."""
    colors = {
        "mahavishnu": "#FF6B6B",      # Red/coral
        "oneiric": "#4ECDC4",          # Emerald
        "crackerjack": "#FFE66D",     # Yellow
        "session-buddy": "#95E1D3", # Light blue
        "akosha": "#DDA0DD",           # Plum
        "dhruva": "#FF8C00",           # Dark orange
        "cross-ecosystem": "#98D8C8", # Teal
    }
    return colors.get(system, "#CCCCCC")


def build_graph(skills: List[SkillMetadata]) -> SkillGraph:
    """
    Build dependency graph from skill relationships.

    Args:
        skills: List of parsed SkillMetadata objects

    Returns:
        SkillGraph with nodes and edges populated
    """
    graph = SkillGraph()

    # Add all skills as nodes
    for skill in skills:
        graph.add_skill(skill)

    # Add edges from "Related Skills" sections
    for skill in skills:
        for related in skill.related_skills:
            # Only add edge if target skill exists
            if related.name in graph.skills:
                graph.add_relationship(
                    source=skill.name,
                    target=related.name,
                    relationship_type=related.relationship_type
                )

    return graph


def find_orphan_skills(graph: SkillGraph) -> List[str]:
    """
    Find skills with no incoming or outgoing edges.

    Args:
        graph: SkillGraph to analyze

    Returns:
        List of orphan skill names
    """
    orphans = []

    for skill_name in graph.skills.keys():
        # Check for no incoming edges (not referenced by anyone)
        in_degree = graph.graph.in_degree(skill_name)
        # Check for no outgoing edges (doesn't reference anyone)
        out_degree = graph.graph.out_degree(skill_name)

        if in_degree == 0 or out_degree == 0:
            orphans.append(skill_name)

    return orphans


def detect_clusters(graph: SkillGraph) -> Dict[str, Set[str]]:
    """
    Detect skill clusters by system.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Dictionary mapping system names to sets of skill names
    """
    clusters: Dict[str, Set[str]] = {}

    for skill_name, skill in graph.skills.items():
        system = skill.system
        if system not in clusters:
            clusters[system] = set()
        clusters[system].add(skill_name)

    return clusters


def analyze_centrality(graph: SkillGraph) -> Dict[str, float]:
    """
    Calculate which skills are most central (important) using PageRank.

    Args:
        graph: SkillGraph to analyze

    Returns:
        Dictionary mapping skill names to PageRank scores
    """
    try:
        # NetworkX 3.x uses pagerank_numpy
        pagerank = nx.pagerank_numpy(graph.graph)
    except AttributeError:
        # Fallback for older NetworkX versions
        pagerank = nx.pagerank(graph.graph)

    # Sort by score descending
    sorted_scores = dict(sorted(
        pagerank.items(),
        key=lambda x: x[1],
        reverse=True
    ))

    return sorted_scores
