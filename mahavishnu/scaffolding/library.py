"""Pattern Library: YAML-based storage and query for architectural patterns."""

from __future__ import annotations

from contextlib import suppress
import logging
import os
from pathlib import Path
import tempfile

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
        self._file_paths = {}
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
            if q in p.name.lower() or q in p.description.lower() or q in " ".join(p.tags).lower()
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
        return self._cache.pop(pattern_id, None) is not None


def atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via a uniquely named temp file.

    The temp file is created with ``O_EXCL`` under a unique name, so
    three separate hazards are closed at once:

    - **Concurrent-writer collision.** With a fixed temp name, every
      writer of the same destination shares one temp file. Whichever
      writer renames first moves the file out from under the others,
      whose rename then fails with ``FileNotFoundError``.
    - **Stale temp reuse.** A temp file left behind by a crashed write
      is reused rather than recreated, so the new content lands in a
      file whose permissions that earlier write decided.
    - **Symlink following.** Opening a fixed temp path with
      ``O_CREAT | O_TRUNC`` follows symlinks, so anything able to write
      into the destination directory can redirect the write -- and its
      truncation -- at an arbitrary file.

    The content is renamed over the destination with ``os.replace``,
    which is atomic on POSIX, and the published file's mode is set with
    ``fchmod`` on the open descriptor so it is never observable at a
    wider mode than requested.
    """
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with suppress(OSError):
            Path(temp_name).unlink()
        raise
