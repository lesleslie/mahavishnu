"""Optimized repository manager with caching and indexing."""
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import aiofiles
from pydantic import ValidationError
import yaml

from .repo_models import Repository, RepositoryManifest


class RepositoryManager:
    """
    Fast repository manager with O(1) lookups.

    Performance improvements:
    - Tag index: O(1) tag filtering vs O(n) scan
    - LRU cache: Repeated queries return instantly
    - Async I/O: Non-blocking config loading
    - Validation: Pydantic ensures data integrity
    """

    def __init__(self, repos_path: Path):
        self.repos_path = repos_path
        self._manifest: RepositoryManifest | None = None

        # Index structures for O(1) lookups
        self._tag_index: dict[str, list[str]] = defaultdict(list)
        self._mcp_index: dict[str, list[str]] = {"native": [], "3rd-party": []}
        self._package_index: dict[str, Repository] = {}
        self._name_index: dict[str, Repository] = {}
        self._all_paths: list[str] = []

    async def load(self) -> None:
        """Load repository manifest asynchronously."""
        async with aiofiles.open(self.repos_path) as f:
            content = await f.read()

        # Validate with Pydantic
        try:
            manifest_data = yaml.safe_load(content)
            self._manifest = RepositoryManifest.model_validate(manifest_data)
        except ValidationError as e:
            raise ValueError(f"Invalid repository manifest: {e}") from e
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse repository manifest: {e}") from e

        # Build indexes
        self._build_indexes()

    def _build_indexes(self) -> None:
        """Build index structures for O(1) lookups."""
        for repo in self._manifest.repos:
            # Package index
            self._package_index[repo.package] = repo

            # Name index
            self._name_index[repo.name] = repo

            # Path list
            self._all_paths.append(str(repo.path))

            # Tag index
            for tag in repo.tags:
                self._tag_index[tag].append(repo.package)

            # MCP index
            if repo.mcp:
                self._mcp_index[repo.mcp].append(repo.package)

    @lru_cache(maxsize=256)  # noqa: B019 - Safe for singleton with explicit invalidation
    def get_by_tag(self, tag: str) -> list[str]:
        """
        Get repository packages by tag.

        O(1) lookup with caching.
        """
        return self._tag_index.get(tag, []).copy()

    @lru_cache(maxsize=128)  # noqa: B019 - Safe for singleton with explicit invalidation
    def get_by_mcp_type(self, mcp_type: str) -> list[str]:
        """Get repositories by MCP type (native or 3rd-party)."""
        return self._mcp_index.get(mcp_type, []).copy()

    def get_by_package(self, package: str) -> Repository | None:
        """Get repository by package name (O(1))."""
        return self._package_index.get(package)

    def get_by_name(self, name: str) -> Repository | None:
        """Get repository by name (O(1))."""
        return self._name_index.get(name)

    def get_all_paths(self) -> list[str]:
        """Get all repository paths."""
        return self._all_paths.copy()

    @lru_cache(maxsize=64)  # noqa: B019 - Safe for singleton with explicit invalidation
    def filter(
        self,
        tags: list[str] | None = None,
        mcp_type: str | None = None,
        language: str | None = None,
    ) -> list[Repository]:
        """
        Filter repositories by multiple criteria.

        All filters are ANDed together.
        Uses cached indexes for O(1) tag lookups.
        """
        results = set(self._manifest.repos)

        # Filter by tags (O(1) with index)
        if tags:
            matched = set()
            for tag in tags:
                matched.update(self.get_by_tag(tag))
            results &= matched

        # Filter by MCP type (O(1) with index)
        if mcp_type:
            matched = set(self.get_by_mcp_type(mcp_type))
            results &= matched

        # Filter by language (O(n) scan, but small n)
        if language:
            results = {
                r for r in results if r.metadata and r.metadata.language == language
            }

        return list(results)

    def search(self, query: str, limit: int = 10) -> list[Repository]:
        """
        Search repositories by name, package, or description.

        Simple text search (can be enhanced with full-text search).
        """
        query_lower = query.lower()
        results = []

        for repo in self._manifest.repos:
            # Search in name
            if query_lower in repo.name:
                results.append(repo)
                continue

            # Search in package
            if query_lower in repo.package:
                results.append(repo)
                continue

            # Search in description
            if query_lower in repo.description.lower():
                results.append(repo)
                continue

        return results[:limit]

    def validate_repos_exist(self) -> list[str]:
        """
        Validate that all repository paths exist.

        Returns list of missing repos.
        """
        missing = []

        for repo in self._manifest.repos:
            if not repo.path.exists():
                missing.append(str(repo.path))

        return missing

    def get_manifest(self) -> RepositoryManifest:
        """Get the validated manifest."""
        if not self._manifest:
            raise RuntimeError("Manifest not loaded. Call load() first.")
        return self._manifest

    def invalidate_cache(self) -> None:
        """Invalidate all caches."""
        self.get_by_tag.cache_clear()
        self.get_by_mcp_type.cache_clear()
        self.filter.cache_clear()
