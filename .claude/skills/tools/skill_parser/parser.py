"""Core skill parser implementation."""

import re
from pathlib import Path
from typing import List, Optional, Tuple, Literal
from dataclasses import dataclass, field, asdict
import yaml


# Regex patterns
FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n(.*)$', re.DOTALL)
RELATED_SKILLS_SECTION = re.compile(
    r'##\s*Related\s+Skills',
    re.MULTILINE | re.IGNORECASE
)
REQUIRED_PATTERN = re.compile(r'\*\*REQUIRED:\*\*\s*`([\w-]+)`')
RELATED_PATTERN = re.compile(r'\*\*RELATED:\*\*\s*`([\w-]+)`')


class SkillParserError(Exception):
    """Base exception for parser errors."""
    pass


class MalformedFrontmatterError(SkillParserError):
    """Raised when YAML frontmatter is malformed."""
    pass


class MissingRequiredFieldError(SkillParserError):
    """Raised when required field is missing."""
    pass


@dataclass
class RelatedSkill:
    """Represents a related skill with relationship type."""
    name: str
    relationship_type: Literal["REQUIRED", "RELATED", "REQUIRED BACKGROUND"]


@dataclass
class SkillMetadata:
    """Complete metadata for a single skill."""
    # Core identity
    name: str
    description: str
    file_path: Path
    directory: Path

    # Classification
    system: str  # mahavishnu, oneiric, crackerjack, session-buddy, akosha, dhruva, cross-ecosystem
    skill_number: Optional[int] = None

    # Searchable content
    keywords: List[str] = field(default_factory=list)
    symptoms: List[str] = field(default_factory=list)
    use_cases: List[str] = field(default_factory=list)

    # Relationships
    related_skills: List[RelatedSkill] = field(default_factory=list)
    referenced_by: List[str] = field(default_factory=list)  # Back-reference

    # Content stats
    word_count: int = 0
    line_count: int = 0
    has_examples: bool = False
    has_flowchart: bool = False

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON export."""
        data = asdict(self)
        # Convert Path objects to strings
        data['file_path'] = str(self.file_path)
        data['directory'] = str(self.directory)
        # Convert RelatedSkill to dict
        data['related_skills'] = [
            {'name': rs.name, 'relationship_type': rs.relationship_type}
            for rs in self.related_skills
        ]
        return data


def parse_skill_file(skill_path: Path) -> SkillMetadata:
    """
    Parse a single SKILL.md file and extract metadata.

    Args:
        skill_path: Path to SKILL.md file

    Returns:
        SkillMetadata object with extracted information

    Raises:
        SkillParserError: If file cannot be parsed
    """
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")

    content = skill_path.read_text(encoding='utf-8')

    # Extract YAML frontmatter
    frontmatter_match = FRONTMATTER_PATTERN.match(content)
    if not frontmatter_match:
        raise MalformedFrontmatterError(
            f"No YAML frontmatter found in {skill_path}"
        )

    frontmatter_yaml = frontmatter_match.group(1)
    markdown_body = frontmatter_match.group(2)

    # Parse YAML frontmatter
    try:
        frontmatter = yaml.safe_load(frontmatter_yaml)
    except yaml.YAMLError as e:
        raise MalformedFrontmatterError(
            f"Invalid YAML in {skill_path}: {e}"
        )

    # Validate required fields
    if not isinstance(frontmatter, dict):
        raise MalformedFrontmatterError(
            f"Frontmatter must be a dict, got {type(frontmatter)} in {skill_path}"
        )

    if 'name' not in frontmatter:
        raise MissingRequiredFieldError(
            f"Missing 'name' field in {skill_path}"
        )
    if 'description' not in frontmatter:
        raise MissingRequiredFieldError(
            f"Missing 'description' field in {skill_path}"
        )

    # Extract metadata
    name = frontmatter['name']
    description = frontmatter['description']

    # Determine system
    system = _determine_system(skill_path, name, description)

    # Extract keywords and symptoms from description
    keywords, symptoms, use_cases = _extract_description_info(description)

    # Parse related skills from markdown body
    related_skills = _extract_related_skills(markdown_body)

    # Calculate content stats
    word_count = len(markdown_body.split())
    line_count = len(markdown_body.split('\n'))
    has_examples = '```' in markdown_body  # Code blocks
    has_flowchart = 'graphviz' in markdown_body or 'dot graph' in markdown_body or 'flowchart' in markdown_body.lower()

    return SkillMetadata(
        name=name,
        description=description,
        file_path=skill_path,
        directory=skill_path.parent,
        system=system,
        keywords=keywords,
        symptoms=symptoms,
        use_cases=use_cases,
        related_skills=related_skills,
        word_count=word_count,
        line_count=line_count,
        has_examples=has_examples,
        has_flowchart=has_flowchart
    )


def _determine_system(
    skill_path: Path,
    name: str,
    description: str
) -> str:
    """
    Determine which system a skill belongs to.

    Strategy:
    1. Check if skill is in cross-ecosystem list
    2. Check directory name
    3. Check for explicit system names in description (Session-Buddy, Mahavishnu, etc.)
    4. Check system-specific keywords (most specific first)
    """
    # Known cross-ecosystem skills
    CROSS_ECOSYSTEM_SKILLS = {
        'mcp-integration',
        'error-handling',
        'observability',
        'oneiric-integration',
        'testing-strategies'
    }

    # Check if explicitly cross-ecosystem
    if name in CROSS_ECOSYSTEM_SKILLS:
        return 'cross-ecosystem'

    # Map directory names to systems
    DIR_TO_SYSTEM = {
        'mahavishnu': 'mahavishnu',
        'oneiric': 'oneiric',
        'crackerjack': 'crackerjack',
        'session-buddy': 'session-buddy',
        'akosha': 'akosha',
        'dhruva': 'dhruva',
    }

    # Check directory
    dir_name = skill_path.parent.name
    if dir_name in DIR_TO_SYSTEM:
        return DIR_TO_SYSTEM[dir_name]

    description_lower = description.lower()

    # Step 1: Check for explicit system name mentions
    EXPLICIT_NAME_PATTERNS = [
        ('session-buddy', ['session-buddy', 'session buddy']),
        ('mahavishnu', ['mahavishnu', 'vishnu']),
        ('crackerjack', ['crackerjack', 'jack']),
        ('oneiric', ['oneiric']),
        ('akosha', ['akosha']),
        ('dhruva', ['dhruva']),
    ]

    for system, patterns in EXPLICIT_NAME_PATTERNS:
        if any(pattern in description_lower for pattern in patterns):
            return system

    # Step 2: Check for dominant keywords (appears multiple times = more specific)
    # Count keyword occurrences for each system
    SYSTEM_KEYWORDS = {
        'session-buddy': ['session', 'capture', 'retention'],
        'dhruva': ['storage', 'backup', 'acid', 'transaction', 'database', 'object'],
        'crackerjack': ['coverage', 'ratchet', 'qc', 'quality gate'],
        'mahavishnu': ['orchestrate', 'adapter', 'pool', 'sweep', 'workflow', 'repository'],
        'oneiric': ['component', 'resolve', 'layered', 'lifecycle'],
        'akosha': ['anomaly', 'semantic', 'correlation', 'time-series', 'knowledge graph'],
    }

    # Count matches for each system
    system_scores = {}
    for system, keywords in SYSTEM_KEYWORDS.items():
        score = sum(description_lower.count(kw) for kw in keywords)
        if score > 0:
            system_scores[system] = score

    # Return system with highest score
    if system_scores:
        return max(system_scores, key=system_scores.get)

    # Default fallback
    return 'cross-ecosystem'


def _extract_description_info(
    description: str
) -> Tuple[List[str], List[str], List[str]]:
    """
    Extract keywords, symptoms, and use cases from description.

    Description format: "Use when [symptoms], [use cases]. Use when..."

    Returns:
        (keywords, symptoms, use_cases) lists
    """
    # Extract keywords (technical terms)
    # Common technical terms in skill descriptions
    TECHNICAL_KEYWORDS = [
        'testing', 'configuration', 'logging', 'mcp', 'adapter',
        'workflow', 'session', 'storage', 'backup', 'quality',
        'coverage', 'observability', 'error', 'component', 'pool',
        'search', 'pattern', 'trend', 'anomaly', 'insight',
        'sweep', 'repository', 'orchestration', 'ratchet',
        'lifecycle', 'resolve', 'distributed', 'tracing'
    ]

    keywords = []
    description_lower = description.lower()
    for kw in TECHNICAL_KEYWORDS:
        if kw in description_lower:
            keywords.append(kw)

    # Extract symptoms (pain points)
    symptom_patterns = [
        'flaky',
        'cannot be sent',
        'borrow',
        'moved value',
        'race condition',
        'timeout',
        'error',
        'failure',
        'crash',
        'bug',
        'issue'
    ]

    symptoms = []
    for pattern in symptom_patterns:
        if re.search(pattern, description_lower):
            symptoms.append(pattern)

    # Extract use cases (actionable tasks)
    use_case_patterns = [
        'implement',
        'add',
        'create',
        'set up',
        'configure',
        'manage',
        'test',
        'debug',
        'integrate'
    ]

    use_cases = []
    for pattern in use_case_patterns:
        if re.search(pattern, description_lower):
            use_cases.append(pattern)

    return keywords, symptoms, use_cases


def _extract_related_skills(markdown_body: str) -> List[RelatedSkill]:
    """
    Parse "Related Skills" section and extract relationships.

    Looks for patterns like:
    - **REQUIRED:** skill-name
    - **RELATED:** skill-name

    Returns:
        List of RelatedSkill objects
    """
    related_skills = []

    # Find "Related Skills" section
    section_match = re.search(
        r'##\s*Related\s+Skills\s*$(.*?)(?=\n##|\Z)',
        markdown_body,
        re.MULTILINE | re.DOTALL | re.IGNORECASE
    )

    if not section_match:
        return related_skills

    section_content = section_match.group(1)

    # Extract REQUIRED skills
    for match in REQUIRED_PATTERN.finditer(section_content):
        skill_name = match.group(1)
        related_skills.append(RelatedSkill(
            name=skill_name,
            relationship_type='REQUIRED'
        ))

    # Extract RELATED skills
    for match in RELATED_PATTERN.finditer(section_content):
        skill_name = match.group(1)
        # Avoid duplicates
        if not any(rs.name == skill_name for rs in related_skills):
            related_skills.append(RelatedSkill(
                name=skill_name,
                relationship_type='RELATED'
            ))

    return related_skills


def parse_all_skills(skills_dir: Path) -> List[SkillMetadata]:
    """
    Parse all skill files in a directory tree.

    Args:
        skills_dir: Root directory containing skill directories

    Returns:
        List of all parsed SkillMetadata objects
    """
    all_skills = []

    # Find all SKILL.md files recursively
    for skill_file in skills_dir.rglob('SKILL.md'):
        try:
            metadata = parse_skill_file(skill_file)
            all_skills.append(metadata)
        except SkillParserError as e:
            print(f"⚠️  Skipping {skill_file}: {e}")
            continue
        except Exception as e:
            print(f"❌ Unexpected error parsing {skill_file}: {e}")
            continue

    # Sort by name for consistent ordering
    all_skills.sort(key=lambda s: s.name)

    return all_skills


def build_reverse_references(skills: List[SkillMetadata]) -> None:
    """
    Build back-references (which skills reference each skill).

    Modifies skills in-place to populate `referenced_by` field.
    """
    # Create lookup
    skill_map = {s.name: s for s in skills}

    # For each skill, find who references it
    for skill in skills:
        for related in skill.related_skills:
            target_skill = skill_map.get(related.name)
            if target_skill:
                target_skill.referenced_by.append(skill.name)
