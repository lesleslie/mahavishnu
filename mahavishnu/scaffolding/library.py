"""Pattern Library: YAML-based storage and query for architectural patterns."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from mahavishnu.scaffolding.models import Pattern

logger = logging.getLogger(__name__)


class PatternLibrary:
    """Load, query, and save pattern YAML files."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = Path(__file__).resolve().parent.parent.parent / "patterns"
        self.root = Path(root)
        self._cache: dict[str, Pattern] = {}
        self._file_paths: dict[str, Path | None] = {}

    def load_all(self) -> list[Pattern]:
        """Load all patterns from the YAML files under root."""
        self._cache.clear()
        self._file_paths: dict[str, Path] = {}
        if not self.root.is_dir():
            return []
        for yaml_file in sorted(self.root.rglob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text())
                if not isinstance(data, dict) or "id" not in data:
                    continue
                pattern = Pattern.model_validate(data)
                object.__setattr__(pattern, "_file_path", yaml_file)
                self._cache[pattern.id] = pattern
                # Track all file paths for duplicate detection
                if pattern.id in self._file_paths:
                    self._file_paths[pattern.id] = None  # None signals duplicate
                else:
                    self._file_paths[pattern.id] = yaml_file
            except Exception as e:
                raise ValueError(f"Failed to load {yaml_file}: {e}") from e
        return list(self._cache.values())

    def get(self, pattern_id: str) -> Pattern | None:
        return self._cache.get(pattern_id)

    def has(self, pattern_id: str) -> bool:
        return pattern_id in self._cache

    def list_category(self, category: str) -> list[Pattern]:
        prefix = category + "/"
        return [p for p in self._cache.values() if p.id.startswith(prefix)]

    def list_all_categories(self) -> list[str]:
        seen: set[str] = set()
        for pid in self._cache:
            cat = pid.split("/")[0]
            seen.add(cat)
        return sorted(seen)

    def search(self, query: str) -> list[Pattern]:
        q = query.lower()
        return [
            p
            for p in self._cache.values()
            if q in p.name.lower()
            or q in p.description.lower()
            or q in " ".join(p.tags).lower()
        ]

    def save(self, pattern: Pattern) -> Path:
        category = pattern.id.split("/")[0]
        name = pattern.id.split("/", 1)[1]
        cat_dir = self.root / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        dest = cat_dir / f"{name}.yaml"
        data = pattern.model_dump(mode="json")
        atomic_write(dest, yaml.dump(data, default_flow_style=False, sort_keys=False))
        self._cache[pattern.id] = pattern
        return dest

    def delete(self, pattern_id: str) -> bool:
        pattern = self._cache.pop(pattern_id, None)
        if pattern is None:
            return False
        return True


def atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via temp file rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.replace(path)
