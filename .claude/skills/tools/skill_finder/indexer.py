"""Search index builder and manager for skill discovery."""

from dataclasses import dataclass, field
import json
from pathlib import Path

from skill_parser import SkillMetadata, build_reverse_references, parse_all_skills


@dataclass
class SearchIndex:
    """Search index for fast skill discovery."""

    skills: dict[str, SkillMetadata] = field(default_factory=dict)
    keyword_index: dict[str, list[str]] = field(default_factory=dict)  # keyword -> skill names
    system_index: dict[str, list[str]] = field(default_factory=dict)  # system -> skill names
    symptom_index: dict[str, list[str]] = field(default_factory=dict)  # symptom -> skill names

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON export."""
        return {
            "skills": {name: skill.to_dict() for name, skill in self.skills.items()},
            "keyword_index": self.keyword_index,
            "system_index": self.system_index,
            "symptom_index": self.symptom_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SearchIndex":
        """Deserialize from dictionary."""
        # Recreate SkillMetadata objects
        from skill_parser import RelatedSkill, SkillMetadata

        skills = {}
        for name, skill_dict in data["skills"].items():
            # Convert related skills back to RelatedSkill objects
            related_skills = [
                RelatedSkill(name=rs["name"], relationship_type=rs["relationship_type"])
                for rs in skill_dict.get("related_skills", [])
            ]
            skill_dict["related_skills"] = related_skills
            skill_dict["file_path"] = Path(skill_dict["file_path"])
            skill_dict["directory"] = Path(skill_dict["directory"])

            skills[name] = SkillMetadata(**skill_dict)

        return cls(
            skills=skills,
            keyword_index=data.get("keyword_index", {}),
            system_index=data.get("system_index", {}),
            symptom_index=data.get("symptom_index", {}),
        )


def build_index(skills_dir: Path) -> SearchIndex:
    """
    Scan all skills and build searchable index.

    Args:
        skills_dir: Root directory containing skill directories

    Returns:
        SearchIndex with all skills indexed
    """
    # Parse all skills
    skills = parse_all_skills(skills_dir)

    # Build reverse references
    build_reverse_references(skills)

    # Create index structures
    index = SearchIndex()

    # Main skills lookup
    for skill in skills:
        index.skills[skill.name] = skill

    # Build keyword index
    for skill in skills:
        for keyword in skill.keywords:
            if keyword not in index.keyword_index:
                index.keyword_index[keyword] = []
            index.keyword_index[keyword].append(skill.name)

    # Build system index
    for skill in skills:
        if skill.system not in index.system_index:
            index.system_index[skill.system] = []
        index.system_index[skill.system].append(skill.name)

    # Build symptom index
    for skill in skills:
        for symptom in skill.symptoms:
            if symptom not in index.symptom_index:
                index.symptom_index[symptom] = []
            index.symptom_index[symptom].append(skill.name)

    return index


def save_index(index: SearchIndex, output_path: Path) -> None:
    """Save index to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index.to_dict(), indent=2))


def load_index(index_path: Path = None) -> SearchIndex:
    """
    Load index from JSON file or build if not exists.

    Args:
        index_path: Path to index.json file. If None, uses default.

    Returns:
        Loaded SearchIndex
    """
    if index_path is None:
        index_path = Path(__file__).parent.parent / "data" / "index.json"

    if index_path.exists():
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return SearchIndex.from_dict(data)
    else:
        # Build index from skills directory
        skills_dir = Path(__file__).parent.parent.parent.parent
        index = build_index(skills_dir)
        save_index(index, index_path)
        return index
