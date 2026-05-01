"""Unit tests for skill parser."""

import pytest
from pathlib import Path
from skill_parser import (
    parse_skill_file,
    parse_all_skills,
    build_reverse_references,
    SkillMetadata,
    MalformedFrontmatterError,
    MissingRequiredFieldError,
)


@pytest.fixture
def sample_skill_file(tmp_path: Path) -> Path:
    """Create a sample SKILL.md file for testing."""
    content = '''---
name: test-skill
description: Use when testing parser functionality and validating YAML frontmatter. Use when implementing parser features.
---

# Test Skill

This is a test skill for parser validation.

## Related Skills

- **REQUIRED:** `other-skill` - Another required skill
- **RELATED:** `another-skill` - Optional related skill

## Examples

```python
def example():
    pass
```
'''
    skill_file = tmp_path / 'test-skill' / 'SKILL.md'
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(content)
    return skill_file


@pytest.fixture
def real_skills_dir() -> Path:
    """Path to the real skills directory."""
    return Path('/Users/les/.claude/skills')


class TestParseSkillFile:
    """Tests for parse_skill_file function."""

    def test_parse_skill_file_basic(self, sample_skill_file: Path):
        """Test basic parsing of skill file."""
        metadata = parse_skill_file(sample_skill_file)

        assert metadata.name == 'test-skill'
        assert metadata.description.startswith('Use when testing')
        assert metadata.file_path == sample_skill_file
        assert 'testing' in metadata.keywords or 'parser' in metadata.keywords
        assert len(metadata.related_skills) == 2
        assert metadata.has_examples is True
        assert metadata.word_count > 0

    def test_parse_skill_file_missing_name(self, tmp_path: Path):
        """Test error when name field is missing."""
        content = '''---
description: Test
---
'''
        skill_file = tmp_path / 'SKILL.md'
        skill_file.write_text(content)

        with pytest.raises(MissingRequiredFieldError):
            parse_skill_file(skill_file)

    def test_parse_skill_file_missing_description(self, tmp_path: Path):
        """Test error when description field is missing."""
        content = '''---
name: test
---
'''
        skill_file = tmp_path / 'SKILL.md'
        skill_file.write_text(content)

        with pytest.raises(MissingRequiredFieldError):
            parse_skill_file(skill_file)

    def test_parse_skill_file_invalid_yaml(self, tmp_path: Path):
        """Test error when YAML is malformed."""
        content = '''---
name: test
description: : invalid yaml [[[
---
'''
        skill_file = tmp_path / 'SKILL.md'
        skill_file.write_text(content)

        with pytest.raises(MalformedFrontmatterError):
            parse_skill_file(skill_file)

    def test_parse_skill_file_no_frontmatter(self, tmp_path: Path):
        """Test error when YAML frontmatter is missing."""
        content = '''# Test Skill

No frontmatter here.
'''
        skill_file = tmp_path / 'SKILL.md'
        skill_file.write_text(content)

        with pytest.raises(MalformedFrontmatterError):
            parse_skill_file(skill_file)

    def test_parse_skill_related_skills_with_backticks(self, sample_skill_file: Path):
        """Test that related skills with backticks are parsed correctly."""
        metadata = parse_skill_file(sample_skill_file)

        related_names = [rs.name for rs in metadata.related_skills]
        assert 'other-skill' in related_names
        assert 'another-skill' in related_names

        # Check relationship types
        other_skill = next(rs for rs in metadata.related_skills if rs.name == 'other-skill')
        assert other_skill.relationship_type == 'REQUIRED'

        another_skill = next(rs for rs in metadata.related_skills if rs.name == 'another-skill')
        assert another_skill.relationship_type == 'RELATED'


class TestParseAllSkills:
    """Tests for parse_all_skills function."""

    def test_parse_all_skills_real_data(self, real_skills_dir: Path):
        """Test parsing all 23 real skills."""
        skills = parse_all_skills(real_skills_dir)

        # Should have 23 ecosystem skills
        assert len(skills) == 23

        # Check known skills exist
        skill_names = {s.name for s in skills}
        assert 'testing-strategies' in skill_names
        assert 'observability' in skill_names
        assert 'orchestrate-workflow' in skill_names
        assert 'error-handling' in skill_names

        # All skills should have descriptions
        for skill in skills:
            assert len(skill.description) > 0
            assert skill.description.startswith('Use when')

    def test_all_skills_have_valid_metadata(self, real_skills_dir: Path):
        """Test that all skills have valid metadata fields."""
        skills = parse_all_skills(real_skills_dir)

        for skill in skills:
            # Core fields
            assert skill.name
            assert skill.description
            assert skill.file_path.exists()
            assert skill.system

            # Statistics
            assert skill.word_count >= 0
            assert skill.line_count >= 0
            assert isinstance(skill.has_examples, bool)
            assert isinstance(skill.has_flowchart, bool)

    def test_system_distribution(self, real_skills_dir: Path):
        """Test that skills are distributed across expected systems."""
        skills = parse_all_skills(real_skills_dir)

        system_counts = {}
        for skill in skills:
            system_counts[skill.system] = system_counts.get(skill.system, 0) + 1

        # Verify expected system counts
        assert system_counts.get('mahavishnu', 0) == 5
        assert system_counts.get('oneiric', 0) == 4
        assert system_counts.get('crackerjack', 0) == 2
        assert system_counts.get('session-buddy', 0) == 3
        assert system_counts.get('akosha', 0) == 2
        assert system_counts.get('dhruva', 0) == 2
        assert system_counts.get('cross-ecosystem', 0) == 5


class TestBuildReverseReferences:
    """Tests for build_reverse_references function."""

    def test_build_reverse_references_simple(self, sample_skill_file: Path):
        """Test building reverse references."""
        # Create a second skill that references the first
        second_content = '''---
name: second-skill
description: Use when testing reverse references.
---

# Second Skill

## Related Skills

- **REQUIRED:** `test-skill`
'''
        second_file = sample_skill_file.parent.parent / 'second-skill' / 'SKILL.md'
        second_file.parent.mkdir(parents=True, exist_ok=True)
        second_file.write_text(second_content)

        skills = [
            parse_skill_file(sample_skill_file),
            parse_skill_file(second_file),
        ]

        build_reverse_references(skills)

        # test-skill should be referenced by second-skill
        test_skill = next(s for s in skills if s.name == 'test-skill')
        assert 'second-skill' in test_skill.referenced_by

    def test_build_reverse_references_real_data(self, real_skills_dir: Path):
        """Test reverse references with real skills."""
        skills = parse_all_skills(real_skills_dir)
        build_reverse_references(skills)

        # error-handling is referenced by many skills
        error_handling = next(s for s in skills if s.name == 'error-handling')
        assert len(error_handling.referenced_by) > 0

        # Some skills should have references
        referenced_skills = [s for s in skills if s.referenced_by]
        assert len(referenced_skills) > 0


class TestSystemClassification:
    """Tests for automatic system classification."""

    def test_cross_ecosystem_skills_explicit(self, real_skills_dir: Path):
        """Test that known cross-ecosystem skills are classified correctly."""
        skills = parse_all_skills(real_skills_dir)

        cross_ecosystem = [
            'mcp-integration',
            'error-handling',
            'observability',
            'oneiric-integration',
            'testing-strategies'
        ]

        for skill_name in cross_ecosystem:
            skill = next(s for s in skills if s.name == skill_name)
            assert skill.system == 'cross-ecosystem', f"{skill_name} should be cross-ecosystem but is {skill.system}"

    def test_explicit_name_classification(self, real_skills_dir: Path):
        """Test that explicit system names in descriptions trigger correct classification."""
        skills = parse_all_skills(real_skills_dir)

        # search-sessions mentions "Session-Buddy" explicitly
        search_sessions = next(s for s in skills if s.name == 'search-sessions')
        assert search_sessions.system == 'session-buddy'

    def test_system_keywords_priority(self, real_skills_dir: Path):
        """Test that more specific keywords take priority over generic ones."""
        skills = parse_all_skills(real_skills_dir)

        # manage-sessions has "session" (3x) and "lifecycle" (1x)
        # Should be classified as session-buddy due to higher keyword score
        manage_sessions = next(s for s in skills if s.name == 'manage-sessions')
        assert manage_sessions.system == 'session-buddy'


class TestSkillMetadata:
    """Tests for SkillMetadata dataclass."""

    def test_to_dict(self, sample_skill_file: Path):
        """Test serialization to dictionary."""
        metadata = parse_skill_file(sample_skill_file)

        data = metadata.to_dict()

        assert data['name'] == metadata.name
        assert data['description'] == metadata.description
        assert isinstance(data['file_path'], str)  # Path converted to string
        assert isinstance(data['directory'], str)
        assert isinstance(data['related_skills'], list)

        # Check RelatedSkill serialization
        if data['related_skills']:
            related = data['related_skills'][0]
            assert 'name' in related
            assert 'relationship_type' in related


@pytest.mark.integration
class TestIntegration:
    """Integration tests for complete workflow."""

    def test_full_parse_workflow(self, real_skills_dir: Path):
        """Test complete parsing workflow."""
        # Parse all skills
        skills = parse_all_skills(real_skills_dir)

        # Build reverse references
        build_reverse_references(skills)

        # Count valid and broken references
        valid_refs = 0
        broken_refs = []

        for skill in skills:
            for related in skill.related_skills:
                target = next((s for s in skills if s.name == related.name), None)
                if target:
                    valid_refs += 1
                    # Verify back-reference exists
                    assert skill.name in target.referenced_by
                else:
                    broken_refs.append(f"{skill.name} → {related.name}")

        # Most references should be valid
        assert valid_refs > 50, f"Only {valid_refs} valid references found"

        # Some known broken references exist (should be fixed in skills)
        # This documents the debt rather than failing the test
        if broken_refs:
            print(f"\nKnown broken references ({len(broken_refs)}):")
            for ref in broken_refs:
                print(f"  - {ref}")

    def test_performance_requirement(self, real_skills_dir: Path):
        """Test that parsing all skills takes less than 1 second."""
        import time

        start = time.time()
        skills = parse_all_skills(real_skills_dir)
        build_reverse_references(skills)
        elapsed = time.time() - start

        assert len(skills) == 23, "Should parse all 23 skills"
        assert elapsed < 1.0, f"Parsing took {elapsed:.2f}s, should be < 1s"
