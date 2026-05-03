"""Export skill graphs to various formats."""

import json
from typing import Any

from .graph import SkillGraph


def export_mermaid(graph: SkillGraph, direction: str = "TD") -> str:
    """
    Export skill graph as Mermaid flowchart.

    Args:
        graph: SkillGraph to export
        direction: Graph direction (TD, TB, LR, RL)

    Returns:
        Mermaid flowchart string
    """
    lines = [f"flowchart {direction}"]

    # Add nodes with styling
    for skill_name, skill in graph.skills.items():
        label = skill_name.replace("-", " ").title()
        color = _get_mermaid_color(skill.system)
        lines.append(f'  {skill_name.replace("-", "_")}["{label}"]')
        lines.append(
            f"  style {skill_name.replace('-', '_')} fill:{color},stroke:#333,stroke-width:2px"
        )

    # Add edges
    for source, target, data in graph.graph.edges(data=True):
        rel_type = data.get("relationship_type", "RELATED")
        style = _get_mermaid_edge_style(rel_type)
        source_id = source.replace("-", "_")
        target_id = target.replace("-", "_")
        lines.append(f"  {source_id} {style} {target_id}")

    return "\n".join(lines)


def export_graphviz(graph: SkillGraph) -> str:
    """
    Export skill graph as Graphviz DOT format.

    Args:
        graph: SkillGraph to export

    Returns:
        Graphviz DOT string
    """
    lines = ["digraph SkillGraph {", "  rankdir=TD;", "  node [shape=box, style=rounded];", ""]

    # Add nodes
    for skill_name, skill in graph.skills.items():
        label = skill_name.replace("-", " ").title()
        color = _get_graphviz_color(skill.system)
        lines.append(
            f'  "{skill_name}" [label="{label}", fillcolor="{color}", style="filled,rounded"];'
        )

    # Add edges
    for source, target, data in graph.graph.edges(data=True):
        rel_type = data.get("relationship_type", "RELATED")
        style = _get_graphviz_edge_style(rel_type)
        lines.append(f'  "{source}" -> "{target}" [{style}];')

    lines.append("}")
    return "\n".join(lines)


def export_json(graph: SkillGraph, indent: int = 2) -> str:
    """
    Export skill graph as JSON.

    Args:
        graph: SkillGraph to export
        indent: JSON indentation

    Returns:
        JSON string
    """
    data = {"nodes": [], "edges": []}

    # Add nodes
    for skill_name, skill in graph.skills.items():
        data["nodes"].append(
            {
                "id": skill_name,
                "label": skill_name,
                "system": skill.system,
                "description": skill.description[:100] + "..."
                if len(skill.description) > 100
                else skill.description,
                "keywords": skill.keywords[:5],
                "color": _get_hex_color(skill.system),
                "related_count": len(skill.related_skills),
                "referenced_by_count": len(skill.referenced_by),
            }
        )

    # Add edges
    for source, target, edge_data in graph.graph.edges(data=True):
        data["edges"].append(
            {
                "source": source,
                "target": target,
                "relationship_type": edge_data.get("relationship_type", "RELATED"),
            }
        )

    return json.dumps(data, indent=indent)


def export_cytoscape(graph: SkillGraph) -> dict[str, Any]:
    """
    Export skill graph as Cytoscape.js JSON format.

    Args:
        graph: SkillGraph to export

    Returns:
        Cytoscape-compatible dictionary
    """
    elements = {"nodes": [], "edges": []}

    # Add nodes
    for skill_name, skill in graph.skills.items():
        elements["nodes"].append(
            {
                "data": {
                    "id": skill_name,
                    "label": skill_name,
                    "system": skill.system,
                    "description": skill.description[:100],
                    "keywords": ", ".join(skill.keywords[:5]),
                    "color": _get_hex_color(skill.system),
                }
            }
        )

    # Add edges
    for source, target, data in graph.graph.edges(data=True):
        elements["edges"].append(
            {
                "data": {
                    "id": f"{source}-{target}",
                    "source": source,
                    "target": target,
                    "label": data.get("relationship_type", "RELATED"),
                }
            }
        )

    return elements


def _get_mermaid_color(system: str) -> str:
    """Get Mermaid color for system."""
    colors = {
        "mahavishnu": "#FF6B6B",
        "oneiric": "#4ECDC4",
        "crackerjack": "#FFE66D",
        "session-buddy": "#95E1D3",
        "akosha": "#DDA0DD",
        "dhruva": "#FF8C00",
        "cross-ecosystem": "#98D8C8",
    }
    return colors.get(system, "#CCCCCC")


def _get_mermaid_edge_style(rel_type: str) -> str:
    """Get Mermaid edge style based on relationship type."""
    rel_upper = rel_type.upper()
    if rel_upper == "REQUIRED":
        return "==>"
    elif rel_upper == "RELATED":
        return "-->"
    elif rel_upper == "OPTIONAL":
        return "-.->"
    else:
        return "-->"


def _get_graphviz_color(system: str) -> str:
    """Get Graphviz color for system."""
    colors = {
        "mahavishnu": "lightcoral",
        "oneiric": "turquoise",
        "crackerjack": "lightyellow",
        "session-buddy": "lightblue",
        "akosha": "plum",
        "dhruva": "darkorange",
        "cross-ecosystem": "lightteal",
    }
    return colors.get(system, "lightgray")


def _get_graphviz_edge_style(rel_type: str) -> str:
    """Get Graphviz edge style based on relationship type."""
    rel_upper = rel_type.upper()
    if rel_upper == "REQUIRED":
        return 'style="bold", color="#333"'
    elif rel_upper == "RELATED":
        return 'style="solid", color="#666"'
    elif rel_upper == "OPTIONAL":
        return 'style="dashed", color="#999"'
    else:
        return 'style="solid", color="#666"'


def _get_hex_color(system: str) -> str:
    """Get hex color for system."""
    colors = {
        "mahavishnu": "#FF6B6B",
        "oneiric": "#4ECDC4",
        "crackerjack": "#FFE66D",
        "session-buddy": "#95E1D3",
        "akosha": "#DDA0DD",
        "dhruva": "#FF8C00",
        "cross-ecosystem": "#98D8C8",
    }
    return colors.get(system, "#CCCCCC")
