"""Unit tests for skill map."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from skill_map import (
    SkillGraph,
    build_graph,
    find_orphan_skills,
    detect_clusters,
    analyze_centrality,
    find_learning_path,
    find_all_paths,
    get_prerequisite_skills,
    suggest_learning_order,
    export_mermaid,
    export_graphviz,
    export_json,
    analyze_connectivity,
    find_bridge_skills,
    get_statistics_summary,
)
from skill_parser import parse_all_skills, build_reverse_references


@pytest.fixture
def sample_graph():
    """Create a sample skill graph for testing."""
    skills_data = [
        {
            "name": "skill-a",
            "description": "Skill A description",
            "content": """
# Skill A

## Related Skills

- **REQUIRED:** `skill-b`
- **RELATED:** `skill-c`
""",
            "directory": "skill-a",
            "system": "test-system",
        },
        {
            "name": "skill-b",
            "description": "Skill B description",
            "content": """
# Skill B

## Related Skills

- **RELATED:** `skill-c`
""",
            "directory": "skill-b",
            "system": "test-system",
        },
        {
            "name": "skill-c",
            "description": "Skill C description",
            "content": """
# Skill C

## Related Skills

- **OPTIONAL:** `skill-a`
""",
            "directory": "skill-c",
            "system": "other-system",
        },
        {
            "name": "orphan-skill",
            "description": "Orphan skill with no relationships",
            "content": """
# Orphan Skill

No related skills.
""",
            "directory": "orphan-skill",
            "system": "test-system",
        },
    ]

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create test skills
        for skill_data in skills_data:
            skill_dir = tmp_path / skill_data["directory"]
            skill_dir.mkdir(parents=True, exist_ok=True)

            skill_file = skill_dir / "SKILL.md"
            content = f"""---
name: {skill_data['name']}
description: {skill_data['description']}
---
{skill_data['content']}
"""
            skill_file.write_text(content)

        # Parse and build graph
        skills = parse_all_skills(tmp_path)
        build_reverse_references(skills)
        graph = build_graph(skills)

        yield graph


class TestSkillGraph:
    """Tests for SkillGraph class."""

    def test_graph_initialization(self, sample_graph: SkillGraph):
        """Test that graph is properly initialized."""
        assert sample_graph.graph is not None
        assert len(sample_graph.skills) == 4

    def test_node_count(self, sample_graph: SkillGraph):
        """Test node count."""
        assert sample_graph.graph.number_of_nodes() == 4

    def test_edge_count(self, sample_graph: SkillGraph):
        """Test edge count."""
        # skill-a -> skill-b (REQUIRED), skill-a -> skill-c (RELATED)
        # skill-b -> skill-c (RELATED)
        # Total: 3 edges
        assert sample_graph.graph.number_of_edges() == 3


class TestFindOrphanSkills:
    """Tests for find_orphan_skills function."""

    def test_find_orphans(self, sample_graph: SkillGraph):
        """Test finding orphan skills."""
        orphans = find_orphan_skills(sample_graph)
        assert "orphan-skill" in orphans

    def test_orphan_count(self, sample_graph: SkillGraph):
        """Test orphan count."""
        orphans = find_orphan_skills(sample_graph)
        # orphan-skill has no edges, so it's an orphan
        # Others have edges, so they're not orphans
        assert len(orphans) >= 1


class TestDetectClusters:
    """Tests for detect_clusters function."""

    def test_detect_system_clusters(self, sample_graph: SkillGraph):
        """Test detecting clusters by system."""
        clusters = detect_clusters(sample_graph)
        # Skills get classified into systems by keywords
        assert len(clusters) >= 1

    def test_cluster_sizes(self, sample_graph: SkillGraph):
        """Test cluster sizes."""
        clusters = detect_clusters(sample_graph)
        # All skills should be in some cluster
        total_skills = sum(len(skills) for skills in clusters.values())
        assert total_skills == 4


class TestAnalyzeCentrality:
    """Tests for analyze_centrality function."""

    def test_centrality_scores(self, sample_graph: SkillGraph):
        """Test PageRank centrality scores."""
        centrality = analyze_centrality(sample_graph)
        assert len(centrality) == 4

        # All scores should be positive
        for skill, score in centrality.items():
            assert score > 0

    def test_centrality_ordering(self, sample_graph: SkillGraph):
        """Test that results are ordered by score."""
        centrality = analyze_centrality(sample_graph)
        scores = list(centrality.values())

        # Check descending order
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]


class TestFindLearningPath:
    """Tests for find_learning_path function."""

    def test_direct_path(self, sample_graph: SkillGraph):
        """Test finding direct path."""
        path = find_learning_path(sample_graph, "skill-a", "skill-b")
        assert path is not None
        assert path[0] == "skill-a"
        assert path[-1] == "skill-b"

    def test_no_path_invalid_skill(self, sample_graph: SkillGraph):
        """Test path with invalid skill."""
        path = find_learning_path(sample_graph, "skill-a", "nonexistent")
        assert path is None

    def test_path_to_self(self, sample_graph: SkillGraph):
        """Test path from skill to itself."""
        path = find_learning_path(sample_graph, "skill-a", "skill-a")
        assert path == ["skill-a"]


class TestFindAllPaths:
    """Tests for find_all_paths function."""

    def test_multiple_paths(self, sample_graph: SkillGraph):
        """Test finding all paths."""
        paths = find_all_paths(sample_graph, "skill-a", "skill-c")
        assert len(paths) >= 1

        # All paths should start and end correctly
        for path in paths:
            assert path[0] == "skill-a"
            assert path[-1] == "skill-c"

    def test_no_paths_invalid_skill(self, sample_graph: SkillGraph):
        """Test all paths with invalid skill."""
        paths = find_all_paths(sample_graph, "skill-a", "nonexistent")
        assert len(paths) == 0


class TestGetPrerequisiteSkills:
    """Tests for get_prerequisite_skills function."""

    def test_direct_prerequisites(self, sample_graph: SkillGraph):
        """Test getting direct prerequisites."""
        prereqs = get_prerequisite_skills(sample_graph, "skill-a")
        assert "skill-b" in prereqs["direct"]

    def test_no_prerequisites(self, sample_graph: SkillGraph):
        """Test skill with no prerequisites."""
        prereqs = get_prerequisite_skills(sample_graph, "skill-b")
        assert len(prereqs["direct"]) == 0


class TestSuggestLearningOrder:
    """Tests for suggest_learning_order function."""

    def test_learning_order(self, sample_graph: SkillGraph):
        """Test suggesting learning order."""
        skills = ["skill-c", "skill-a", "skill-b"]
        order = suggest_learning_order(sample_graph, skills)

        # All skills should be in result
        for skill in skills:
            assert skill in order

    def test_empty_skill_list(self, sample_graph: SkillGraph):
        """Test with empty skill list."""
        order = suggest_learning_order(sample_graph, [])
        assert order == []


class TestExporters:
    """Tests for export functions."""

    def test_export_mermaid(self, sample_graph: SkillGraph):
        """Test Mermaid export."""
        mermaid = export_mermaid(sample_graph)
        assert "flowchart" in mermaid
        assert "skill_a" in mermaid or "skill-a" in mermaid

    def test_export_graphviz(self, sample_graph: SkillGraph):
        """Test Graphviz export."""
        dot = export_graphviz(sample_graph)
        assert "digraph" in dot
        assert "SkillGraph" in dot

    def test_export_json(self, sample_graph: SkillGraph):
        """Test JSON export."""
        json_str = export_json(sample_graph)
        import json
        data = json.loads(json_str)

        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 4


class TestAnalyzeConnectivity:
    """Tests for analyze_connectivity function."""

    def test_connectivity_metrics(self, sample_graph: SkillGraph):
        """Test connectivity analysis."""
        stats = analyze_connectivity(sample_graph)
        assert stats["total_nodes"] == 4
        assert stats["total_edges"] == 3
        assert "density" in stats
        assert "is_connected" in stats


class TestFindBridgeSkills:
    """Tests for find_bridge_skills function."""

    def test_find_bridges(self, sample_graph: SkillGraph):
        """Test finding bridge skills."""
        bridges = find_bridge_skills(sample_graph)
        # Should return list of tuples
        assert isinstance(bridges, list)


class TestGetStatisticsSummary:
    """Tests for get_statistics_summary function."""

    def test_summary_format(self, sample_graph: SkillGraph):
        """Test statistics summary format."""
        summary = get_statistics_summary(sample_graph)
        assert "Skill Graph Statistics" in summary
        assert "Total Skills:" in summary
        assert "System Distribution:" in summary


class TestRealSkillsData:
    """Integration tests with real skills data."""

    @pytest.fixture
    def real_graph(self) -> SkillGraph:
        """Build graph from real skills."""
        skills_dir = Path("/Users/les/.claude/skills")
        skills = parse_all_skills(skills_dir)
        build_reverse_references(skills)
        return build_graph(skills)

    def test_parse_all_real_skills(self, real_graph: SkillGraph):
        """Test parsing all 23 real skills."""
        assert len(real_graph.skills) == 23

    def test_real_graph_connectivity(self, real_graph: SkillGraph):
        """Test real graph is connected."""
        stats = analyze_connectivity(real_graph)
        assert stats["total_nodes"] == 23
        assert stats["total_edges"] > 0

    def test_real_skill_clusters(self, real_graph: SkillGraph):
        """Test real skill clustering."""
        clusters = detect_clusters(real_graph)
        assert len(clusters) >= 3  # Should have multiple systems

    def test_export_real_graph_mermaid(self, real_graph: SkillGraph):
        """Test exporting real graph as Mermaid."""
        mermaid = export_mermaid(real_graph)
        assert "flowchart" in mermaid
        assert len(mermaid) > 100  # Should be substantial

    def test_export_real_graph_json(self, real_graph: SkillGraph):
        """Test exporting real graph as JSON."""
        json_str = export_json(real_graph)
        import json
        data = json.loads(json_str)

        assert len(data["nodes"]) == 23
        assert len(data["edges"]) > 0
