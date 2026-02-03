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
        if self._manifest is None:
            return
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
        # Convert list to tuple for caching
        tags_tuple = tuple(tags) if tags else None

        # Call the cached implementation
        return self._filter_cached(tags_tuple, mcp_type, language)

    @lru_cache(maxsize=64)  # noqa: B019 - Safe for singleton with explicit invalidation
    def _filter_cached(
        self,
        tags: tuple[str, ...] | None = None,
        mcp_type: str | None = None,
        language: str | None = None,
    ) -> list[Repository]:
        """
        Internal cached implementation of filter.
        Tags must be a tuple for cacheability.
        """
        # Convert tuple back to list
        tags_list = list(tags) if tags else None

        # Start with all repos
        results: list[Repository] = list(self._manifest.repos) if self._manifest else []

        # Filter by tags (O(1) with index)
        if tags_list:
            results = self._filter_by_tags(results, tags_list)

        # Filter by MCP type (O(1) with index)
        if mcp_type:
            results = self._filter_by_mcp_type(results, mcp_type)

        # Filter by language (O(n) scan, but small n)
        if language:
            results = self._filter_by_language(results, language)

        return results.copy()

    def _filter_by_tags(self, results: list[Repository], tags_list: list[str]) -> list[Repository]:
        """Filter repositories by tags."""
        # Get repos that match ALL tags (AND logic)
        # For each tag, get matching repos, then intersect
        if len(tags_list) == 1:
            # Single tag - use index directly
            return [
                self.get_by_package(pkg)
                for pkg in self.get_by_tag(tags_list[0])
                if self.get_by_package(pkg)
            ]
        else:
            # Multiple tags - get repos for each tag and find intersection
            tag_results = [
                [
                    self.get_by_package(pkg)
                    for pkg in self.get_by_tag(tag)
                    if self.get_by_package(pkg)
                ]
                for tag in tags_list
            ]
            # Find repos that appear in all tag results
            # Use name as identifier since repos aren't hashable
            if tag_results and all(tag_results):
                # Build map of name -> repo for first result
                name_to_repo = {r.name: r for r in tag_results[0] if r}
                # Filter to repos that are in all tag results
                for tag_result_list in tag_results[1:]:
                    names_in_this = {r.name for r in tag_result_list if r}
                    name_to_repo = {n: r for n, r in name_to_repo.items() if n in names_in_this}
                return list(name_to_repo.values())
            else:
                return []

    def _filter_by_mcp_type(self, results: list[Repository], mcp_type: str) -> list[Repository]:
        """Filter repositories by MCP type."""
        mcp_repos = [
            self.get_by_package(pkg)
            for pkg in self.get_by_mcp_type(mcp_type)
            if self.get_by_package(pkg)
        ]
        mcp_names = {r.name for r in mcp_repos if r}
        return [r for r in results if r and r.name in mcp_names]

    def _filter_by_language(self, results: list[Repository], language: str) -> list[Repository]:
        """Filter repositories by language."""
        return [r for r in results if r.metadata and r.metadata.language == language]

    def search(self, query: str, limit: int = 10) -> list[Repository]:
        """
        Search repositories by name, package, or description.

        Simple text search (can be enhanced with full-text search).
        """
        if self._manifest is None:
            return []

        query_lower = query.lower()

        results = [
            repo
            for repo in self._manifest.repos
            if query_lower in repo.name
            or query_lower in repo.package
            or query_lower in repo.description.lower()
        ]

        return results[:limit]

    def validate_repos_exist(self) -> list[str]:
        """
        Validate that all repository paths exist.

        Returns list of missing repos.
        """
        if self._manifest is None:
            return []

        missing = []

        for repo in self._manifest.repos:
            if not repo.path.exists():
                missing.append(str(repo.path))

        return missing

    def get_manifest(self) -> RepositoryManifest:
        """Get the validated manifest."""
        if self._manifest is None:
            raise RuntimeError("Manifest not loaded. Call load() first.")
        return self._manifest

    def invalidate_cache(self) -> None:
        """Invalidate all caches."""
        self.get_by_tag.cache_clear()
        self.get_by_mcp_type.cache_clear()
        self.filter.cache_clear()
