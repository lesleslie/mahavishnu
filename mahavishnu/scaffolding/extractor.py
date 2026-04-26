"""Pattern Extractor: manual curation and AI suggestion from existing projects."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from mahavishnu.scaffolding.models import Pattern

logger = logging.getLogger(__name__)


class PatternDraft:
    """A suggested pattern not yet approved for the library."""

    def __init__(
        self,
        category: str,
        name: str,
        dirs: list[dict],
        files: list[dict],
        confidence: float,
        source_repos: list[str],
    ) -> None:
        self.category = category
        self.name = name
        self.dirs = dirs
        self.files = files
        self.confidence = confidence
        self.source_repos = source_repos

    def to_pattern_dict(self) -> dict:
        return {
            "schema_version": 1,
            "id": f"{self.category}/{self.name}",
            "name": f"{self.category}/{self.name}".title(),
            "description": f"Auto-suggested pattern from {', '.join(self.source_repos)}",
            "version": "0.1.0-draft",
            "source_repos": self.source_repos,
            "confidence": round(self.confidence, 2),
            "depends": [],
            "tags": [self.category, "auto-suggested"],
            "structure": {
                "dirs": self.dirs,
                "files": self.files,
            },
            "templates": {},
            "slots": {},
        }


class PatternExtractor:
    """Extract patterns from existing projects."""

    def __init__(self) -> None:
        self._repo_paths: dict[str, Path] = {}

    def register_repo(self, name: str, path: Path | str) -> None:
        self._repo_paths[name] = Path(path)

    def create_draft_from_project(
        self,
        repo_name: str,
        category: str,
        name: str,
        description: str = "",
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> PatternDraft:
        repo_path = self._repo_paths.get(repo_name)
        if repo_path is None:
            raise ValueError(f"Unknown repo: {repo_name}")

        include_re = [re.compile(p) for p in (include_patterns or [r".*"])]
        exclude_re = [
            re.compile(p)
            for p in (
                exclude_patterns
                or [r"^__pycache__$", r"^\.git$", r"^\.venv$"]
            )
        ]

        dirs: list[dict] = []
        files: list[dict] = []

        for item in sorted(repo_path.rglob("*")):
            rel = item.relative_to(repo_path).as_posix()
            if any(ex.search(rel) for ex in exclude_re):
                continue
            if not any(inc.search(rel) for inc in include_re):
                continue

            if item.is_dir():
                dirs.append(
                    {"path": rel + "/", "required": False, "description": ""}
                )
            elif item.is_file() and item.suffix in {
                ".py",
                ".yaml",
                ".yml",
                ".toml",
                ".html",
                ".css",
                ".js",
            }:
                files.append(
                    {"path": rel, "required": False, "description": ""}
                )

        return PatternDraft(
            category=category,
            name=name,
            dirs=dirs,
            files=files,
            confidence=1.0,
            source_repos=[repo_name],
        )

    def suggest_patterns(
        self,
        min_prevalence: float = 0.7,
    ) -> list[PatternDraft]:
        if len(self._repo_paths) < 2:
            logger.info("Need at least 2 repos to suggest patterns")
            return []

        repo_structures: dict[str, list[str]] = {}
        for name, path in self._repo_paths.items():
            repo_structures[name] = _get_sorted_path_list(path)

        shared_dirs = _find_common_subtrees(repo_structures, min_prevalence)

        drafts: list[PatternDraft] = []
        for dir_path, prevalence in shared_dirs.items():
            shared_files = _find_common_files(
                repo_structures, dir_path, min_prevalence
            )
            category = _infer_category(dir_path)
            name = dir_path.rstrip("/").replace("/", "-")
            drafts.append(
                PatternDraft(
                    category=category,
                    name=name,
                    dirs=[
                        {
                            "path": dir_path,
                            "required": True,
                            "description": "",
                        }
                    ],
                    files=[
                        {
                            "path": f"{dir_path}/{f}",
                            "required": False,
                            "description": "",
                        }
                        for f in shared_files
                    ],
                    confidence=prevalence,
                    source_repos=[
                        n
                        for n in repo_structures
                        if dir_path
                        in " ".join(repo_structures[n])
                    ],
                )
            )

        return sorted(drafts, key=lambda d: -d.confidence)


def _get_sorted_path_list(repo_path: Path) -> list[str]:
    paths = []
    for item in sorted(repo_path.rglob("*")):
        rel = item.relative_to(repo_path).as_posix()
        if item.is_file():
            paths.append(rel)
    return paths


def _find_common_subtrees(
    repo_structures: dict[str, list[str]], min_prevalence: float
) -> dict[str, float]:
    all_files: set[str] = set()
    for files in repo_structures.values():
        all_files.update(files)

    n_repos = len(repo_structures)
    result: dict[str, float] = {}
    for file_path in all_files:
        dir_path = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
        if not dir_path:
            continue
        count = sum(
            1 for files in repo_structures.values() if dir_path in " ".join(files)
        )
        prevalence = count / n_repos
        if prevalence >= min_prevalence:
            result[dir_path] = max(result.get(dir_path, 0), prevalence)

    return result


def _find_common_files(
    repo_structures: dict[str, list[str]], dir_path: str, min_prevalence: float
) -> list[str]:
    file_counts: dict[str, int] = {}
    n_repos = len(repo_structures)
    for files in repo_structures.values():
        matching = [
            f.split("/")[-1] for f in files if f.startswith(dir_path + "/")
        ]
        for f in matching:
            file_counts[f] = file_counts.get(f, 0) + 1
    return sorted(f for f, c in file_counts.items() if c / n_repos >= min_prevalence)


def _infer_category(dir_path: str) -> str:
    if dir_path.startswith("adapter"):
        return "adapters"
    if dir_path.startswith("component") or dir_path.startswith("template"):
        return "components"
    if dir_path in ("deploy", "deployment", "docker"):
        return "deployment"
    if dir_path in ("settings", "config"):
        return "scaffolding"
    return "scaffolding"
