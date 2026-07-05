"""Unit tests for skill finder."""

from pathlib import Path

import pytest
from skill_finder import (
    SearchIndex,
    build_index,
    exact_search,
    fuzzy_search,
    load_index,
    save_index,
    search_by_keyword,
    search_by_system,
)
from skill_parser import (
    SkillMetadata,
    build_reverse_references,
    parse_all_skills,
)


@pytest.fixture
def sample_skills_dir(tmp_path: Path) -> Path:
    """Create a sample skills directory for testing."""
    # Create test skills - each in its own directory
    skills_data = [
        {
            "name": "test-workflow",
            "description": "Use when orchestrating workflows and managing adapters.",
            "content": """
# Test Workflow Skill

## Related Skills

- **REQUIRED:** `test-error`
- **RELATED:** `test-testing`

## Examples

```python
def workflow():
    pass
```
""",
            "directory": "test-workflow",
        },
        {
            "name": "test-error",
            "description": "Use when handling errors and implementing error recovery.",
            "content": """
# Test Error Skill

## Related Skills

- **RELATED:** `test-workflow`
""",
            "directory": "test-error",
        },
        {
            "name": "test-testing",
            "description": "Use when implementing testing strategies and quality checks.",
            "content": """
# Test Testing Skill

## Examples

```python
def test_example():
    assert True
```
""",
            "directory": "test-testing",
        },
    ]

    for skill_data in skills_data:
        skill_dir = tmp_path / skill_data["directory"]
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"
        content = f"""---
name: {skill_data["name"]}
description: {skill_data["description"]}
---
{skill_data["content"]}
"""
        skill_file.write_text(content)

    return tmp_path


@pytest.fixture
def sample_index(sample_skills_dir: Path) -> SearchIndex:
    """Build a sample search index."""
    skills = parse_all_skills(sample_skills_dir)
    build_reverse_references(skills)
    return build_index(sample_skills_dir)


class TestSearchIndex:
    """Tests for SearchIndex class."""

    def test_index_structure(self, sample_index: SearchIndex):
        """Test that index has correct structure."""
        assert len(sample_index.skills) == 3
        assert len(sample_index.keyword_index) > 0
        assert len(sample_index.system_index) > 0

    def test_skills_lookup(self, sample_index: SearchIndex):
        """Test main skills lookup."""
        assert "test-workflow" in sample_index.skills
        assert "test-error" in sample_index.skills
        assert "test-testing" in sample_index.skills

        skill = sample_index.skills["test-workflow"]
        assert isinstance(skill, SkillMetadata)
        assert skill.name == "test-workflow"

    def test_keyword_index(self, sample_index: SearchIndex):
        """Test keyword index lookup."""
        # Should have keywords from descriptions
        assert any("workflow" in kw.lower() for kw in sample_index.keyword_index)
        assert any("error" in kw.lower() for kw in sample_index.keyword_index)

    def test_system_index(self, sample_index: SearchIndex):
        """Test system index lookup."""
        # test-workflow has "workflow" keyword which maps to mahavishnu
        # test-error and test-testing are cross-ecosystem
        assert "mahavishnu" in sample_index.system_index
        assert "cross-ecosystem" in sample_index.system_index

        mahavishnu_skills = sample_index.system_index["mahavishnu"]
        assert "test-workflow" in mahavishnu_skills

        cross_skills = sample_index.system_index["cross-ecosystem"]
        assert "test-error" in cross_skills
        assert "test-testing" in cross_skills

    def test_symptom_index(self, sample_index: SearchIndex):
        """Test symptom index lookup."""
        # Check that symptom index exists
        assert isinstance(sample_index.symptom_index, dict)


class TestFuzzySearch:
    """Tests for fuzzy_search function."""

    def test_exact_name_match(self, sample_index: SearchIndex):
        """Test exact skill name match (100% score)."""
        results = fuzzy_search("test-workflow", sample_index)

        assert len(results) == 1
        assert results[0].skill_name == "test-workflow"
        assert results[0].score == 1.0
        assert results[0].match_type == "exact"

    def test_keyword_match(self, sample_index: SearchIndex):
        """Test keyword match (80-95% score)."""
        results = fuzzy_search("workflow", sample_index)

        assert len(results) > 0
        workflow_results = [r for r in results if "workflow" in r.skill_name.lower()]
        assert len(workflow_results) > 0

        result = workflow_results[0]
        assert result.match_type == "keyword"
        assert 0.80 <= result.score <= 0.95

    def test_description_match(self, sample_index: SearchIndex):
        """Test description match (can exceed 80% for early-position matches)."""
        results = fuzzy_search("orchestrating", sample_index)

        orchestrating_results = [
            r
            for r in results
            if "orchestrating" in sample_index.skills[r.skill_name].description.lower()
        ]
        assert len(orchestrating_results) > 0

        result = orchestrating_results[0]
        assert result.match_type == "description"
        # Score can exceed 80% if match is at the beginning of description
        assert 0.60 <= result.score <= 0.90

    def test_name_substring_match(self, sample_index: SearchIndex):
        """Test skill name substring match (70-85% score)."""
        results = fuzzy_search("test", sample_index)

        # Should find all test-* skills (exact match "testing" will rank higher)
        test_skills = [r for r in results if r.skill_name.startswith("test-")]
        assert len(test_skills) >= 2

        for result in test_skills:
            if result.match_type == "name_substring":
                assert 0.70 <= result.score <= 0.85

    def test_no_results(self, sample_index: SearchIndex):
        """Test search with no results."""
        results = fuzzy_search("nonexistent-query-xyz", sample_index)
        assert len(results) == 0

    def test_limit_results(self, sample_index: SearchIndex):
        """Test limiting number of results."""
        results = fuzzy_search("test", sample_index, limit=2)
        assert len(results) <= 2

    def test_score_ordering(self, sample_index: SearchIndex):
        """Test that results are ordered by score."""
        results = fuzzy_search("test", sample_index)

        # Check descending order
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score


class TestExactSearch:
    """Tests for exact_search function."""

    def test_exact_match(self, sample_index: SearchIndex):
        """Test exact skill name match."""
        results = exact_search("test-workflow", sample_index)

        assert len(results) == 1
        assert results[0] == "test-workflow"

    def test_case_insensitive(self, sample_index: SearchIndex):
        """Test that exact search is case-insensitive."""
        results = exact_search("TEST-WORKFLOW", sample_index)

        assert len(results) == 1
        assert results[0] == "test-workflow"

    def test_no_match(self, sample_index: SearchIndex):
        """Test exact search with no match."""
        results = exact_search("nonexistent-skill", sample_index)
        assert len(results) == 0


class TestSearchBySystem:
    """Tests for search_by_system function."""

    def test_mahavishnu_system(self, sample_index: SearchIndex):
        """Test searching by mahavishnu system."""
        results = search_by_system("mahavishnu", sample_index)

        assert len(results) > 0
        assert "test-workflow" in results

    def test_cross_ecosystem_system(self, sample_index: SearchIndex):
        """Test searching by cross-ecosystem system."""
        results = search_by_system("cross-ecosystem", sample_index)

        # test-error and test-testing are cross-ecosystem (test-workflow is mahavishnu)
        assert len(results) >= 2
        assert "test-error" in results
        assert "test-testing" in results

    def test_nonexistent_system(self, sample_index: SearchIndex):
        """Test searching for nonexistent system."""
        results = search_by_system("nonexistent-system", sample_index)
        assert len(results) == 0


class TestSearchByKeyword:
    """Tests for search_by_keyword function."""

    def test_keyword_match(self, sample_index: SearchIndex):
        """Test searching by keyword."""
        results = search_by_keyword("workflow", sample_index)

        assert len(results) > 0
        assert "test-workflow" in results

    def test_case_insensitive(self, sample_index: SearchIndex):
        """Test that keyword search is case-insensitive."""
        results_lower = search_by_keyword("workflow", sample_index)
        results_upper = search_by_keyword("WORKFLOW", sample_index)

        assert set(results_lower) == set(results_upper)

    def test_partial_keyword_match(self, sample_index: SearchIndex):
        """Test partial keyword matching."""
        # Should match keywords containing "workflow"
        results = search_by_keyword("workflow", sample_index)
        assert len(results) > 0
        # test-workflow has "workflow" keyword
        assert "test-workflow" in results


class TestIndexPersistence:
    """Tests for index save/load functionality."""

    def test_save_and_load_index(self, sample_skills_dir: Path, tmp_path: Path):
        """Test saving and loading index."""
        # Build and save index
        skills = parse_all_skills(sample_skills_dir)
        build_reverse_references(skills)
        index = build_index(sample_skills_dir)

        index_path = tmp_path / "test_index.json"
        save_index(index, index_path)

        # Load index
        loaded_index = load_index(index_path)

        # Verify
        assert len(loaded_index.skills) == len(index.skills)

        for skill_name in index.skills:
            assert skill_name in loaded_index.skills
            loaded_skill = loaded_index.skills[skill_name]
            original_skill = index.skills[skill_name]

            assert loaded_skill.name == original_skill.name
            assert loaded_skill.description == original_skill.description
            assert loaded_skill.system == original_skill.system

    def test_load_nonexistent_index(self, sample_skills_dir: Path, tmp_path: Path):
        """Test loading index that doesn't exist (should build new one)."""
        non_existent_path = tmp_path / "nonexistent_index.json"

        # Should build new index if file doesn't exist
        index = load_index(non_existent_path)

        # Verify it was built from the skills directory
        # Note: This test assumes sample_skills_dir structure
        assert len(index.skills) > 0


class TestRealSkillsData:
    """Integration tests with real skills data."""

    @pytest.fixture
    def real_skills_dir(self) -> Path:
        """Path to the real skills directory."""
        return Path("/Users/les/.claude/skills")

    @pytest.fixture
    def real_index(self, real_skills_dir: Path) -> SearchIndex:
        """Build index from real skills."""
        skills = parse_all_skills(real_skills_dir)
        build_reverse_references(skills)
        return build_index(real_skills_dir)

    def test_parse_all_real_skills(self, real_index: SearchIndex):
        """Test parsing all 23 real skills."""
        assert len(real_index.skills) == 23

    def test_known_skills_exist(self, real_index: SearchIndex):
        """Test that known skills exist in index."""
        known_skills = [
            "testing-strategies",
            "observability",
            "error-handling",
            "orchestrate-workflow",
            "mcp-integration",
        ]

        for skill_name in known_skills:
            assert skill_name in real_index.skills

    def test_search_real_skills(self, real_index: SearchIndex):
        """Test searching real skills."""
        # Test workflow-related search
        results = fuzzy_search("workflow", real_index)
        assert len(results) > 0

        # Test testing-related search
        results = fuzzy_search("testing", real_index)
        assert len(results) > 0

        # Test system-specific search
        mahavishnu_skills = search_by_system("mahavishnu", real_index)
        assert len(mahavishnu_skills) > 0

    def test_system_distribution(self, real_index: SearchIndex):
        """Test that skills are distributed across systems."""
        system_counts = {}
        for skill in real_index.skills.values():
            system = skill.system
            system_counts[system] = system_counts.get(system, 0) + 1

        # Should have multiple systems
        assert len(system_counts) >= 3

        # Cross-ecosystem should have skills
        assert "cross-ecosystem" in system_counts
        assert system_counts["cross-ecosystem"] >= 5

    def test_keyword_coverage(self, real_index: SearchIndex):
        """Test that keyword index has good coverage."""
        # Should have keywords from common domains
        assert any("workflow" in kw.lower() for kw in real_index.keyword_index)
        assert any("testing" in kw.lower() for kw in real_index.keyword_index)
        assert any("error" in kw.lower() for kw in real_index.keyword_index)

    def test_symptom_coverage(self, real_index: SearchIndex):
        """Test that symptom index captures symptoms."""
        # Should have some symptoms indexed
        assert len(real_index.symptom_index) > 0

    def test_performance_requirement(self, real_skills_dir: Path):
        """Test that search performance is acceptable."""
        import time

        skills = parse_all_skills(real_skills_dir)
        build_reverse_references(skills)
        index = build_index(real_skills_dir)

        # Search should be fast
        start = time.time()
        results = fuzzy_search("workflow", index)
        elapsed = time.time() - start

        assert len(results) > 0
        assert elapsed < 0.1, f"Search took {elapsed:.3f}s, should be < 0.1s"
