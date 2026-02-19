"""Cross-Repository Task Search for Mahavishnu.

Provides search capabilities across multiple repositories:
- Full-text search in task fields
- Tag-based search
- Combined filtering with search
- Search result ranking and highlighting

Usage:
    from mahavishnu.core.cross_repo_search import CrossRepoSearch, SearchCriteria

    search = CrossRepoSearch(task_store)

    # Text search
    criteria = SearchCriteria(query="authentication bug")
    results = await search.search(criteria)

    # Search with filters
    criteria = SearchCriteria(
        query="api",
        repo_names=["mahavishnu"],
        statuses=[TaskStatus.IN_PROGRESS],
    )
    results = await search.search(criteria)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority, TaskStore, TaskListFilter

logger = logging.getLogger(__name__)


class SearchType(str, Enum):
    """Type of search to perform."""

    TEXT = "text"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


@dataclass
class SearchCriteria:
    """Criteria for cross-repository task search.

    Attributes:
        query: Search query string
        search_type: Type of search (text, semantic, hybrid)
        repo_names: Filter to specific repositories
        statuses: Filter to specific statuses
        priorities: Filter to specific priorities
        tags: Filter to tasks with these tags
        search_fields: Fields to search in (default: all text fields)
        limit: Maximum number of results
        min_score: Minimum relevance score (0.0 to 1.0)
    """

    query: str
    search_type: SearchType = SearchType.TEXT
    repo_names: list[str] | None = None
    statuses: list[TaskStatus] | None = None
    priorities: list[TaskPriority] | None = None
    tags: list[str] | None = None
    search_fields: list[str] | None = None
    limit: int = 50
    min_score: float = 0.0


@dataclass
class SearchMatch:
    """A single match within a search result.

    Attributes:
        field: Field where match was found
        snippet: Text snippet with match highlighted
        score: Relevance score for this match (0.0 to 1.0)
        positions: Character positions of matches in original text
    """

    field: str
    snippet: str
    score: float
    positions: list[tuple[int, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "field": self.field,
            "snippet": self.snippet,
            "score": self.score,
            "positions": self.positions,
        }


@dataclass
class SearchResult:
    """A single search result with task and match information.

    Attributes:
        task: The matching task
        matches: List of field matches
        overall_score: Combined relevance score (0.0 to 1.0)
        search_type: Type of search that produced this result
    """

    task: Task
    matches: list[SearchMatch] = field(default_factory=list)
    overall_score: float = 0.0
    search_type: SearchType = SearchType.TEXT

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "task": self.task.to_dict(),
            "matches": [m.to_dict() for m in self.matches],
            "overall_score": self.overall_score,
            "search_type": self.search_type.value,
        }


class CrossRepoSearch:
    """Searches tasks across multiple repositories.

    Provides flexible search with:
    - Full-text search in task fields
    - Tag-based filtering
    - Status and priority filtering
    - Repository filtering
    - Result ranking and highlighting

    Example:
        search = CrossRepoSearch(task_store)

        # Simple text search
        results = await search.search(SearchCriteria(query="bug"))

        # Search with filters
        results = await search.search(SearchCriteria(
            query="api",
            repo_names=["mahavishnu"],
            statuses=[TaskStatus.IN_PROGRESS],
            tags=["backend"],
        ))
    """

    # Default fields to search in
    DEFAULT_SEARCH_FIELDS = ["title", "description", "tags"]

    # Field weights for scoring
    FIELD_WEIGHTS = {
        "title": 3.0,  # Title matches are most important
        "tags": 2.0,   # Tag matches are significant
        "description": 1.0,  # Description matches are baseline
    }

    def __init__(
        self,
        task_store: TaskStore,
        vector_search: Any = None,  # Optional VectorSearch for semantic search
    ) -> None:
        """Initialize the search.

        Args:
            task_store: TaskStore instance for task queries
            vector_search: Optional VectorSearch for semantic search
        """
        self.task_store = task_store
        self.vector_search = vector_search

    async def search(self, criteria: SearchCriteria) -> list[SearchResult]:
        """Search for tasks matching the criteria.

        Args:
            criteria: Search criteria

        Returns:
            List of SearchResult ranked by relevance
        """
        # Fetch candidate tasks
        tasks = await self._fetch_candidate_tasks(criteria)

        # Apply search
        if criteria.search_type == SearchType.SEMANTIC and self.vector_search:
            results = await self._semantic_search(tasks, criteria)
        elif criteria.search_type == SearchType.HYBRID and self.vector_search:
            results = await self._hybrid_search(tasks, criteria)
        else:
            results = await self._text_search(tasks, criteria)

        # Apply post-search filters
        results = self._apply_filters(results, criteria)

        # Sort by score (descending)
        results.sort(key=lambda r: r.overall_score, reverse=True)

        # Filter by minimum score
        if criteria.min_score > 0:
            results = [r for r in results if r.overall_score >= criteria.min_score]

        # Apply limit
        return results[:criteria.limit]

    async def _fetch_candidate_tasks(self, criteria: SearchCriteria) -> list[Task]:
        """Fetch candidate tasks for searching."""
        # For now, fetch all tasks and filter in-memory
        # In production, this would use more efficient queries
        task_filter = TaskListFilter(limit=10000)

        if criteria.statuses and len(criteria.statuses) == 1:
            task_filter.status = criteria.statuses[0]

        if criteria.priorities and len(criteria.priorities) == 1:
            task_filter.priority = criteria.priorities[0]

        if criteria.tags and len(criteria.tags) == 1:
            task_filter.tags = criteria.tags

        return await self.task_store.list(task_filter)

    async def _text_search(
        self,
        tasks: list[Task],
        criteria: SearchCriteria,
    ) -> list[SearchResult]:
        """Perform full-text search."""
        if not criteria.query:
            # Empty query returns all tasks with neutral score
            return [
                SearchResult(
                    task=task,
                    matches=[],
                    overall_score=0.5,
                    search_type=SearchType.TEXT,
                )
                for task in tasks
            ]

        results: list[SearchResult] = []
        search_fields = criteria.search_fields or self.DEFAULT_SEARCH_FIELDS

        # Parse query into terms
        terms = self._parse_query(criteria.query)

        for task in tasks:
            matches: list[SearchMatch] = []

            for field in search_fields:
                field_value = self._get_field_value(task, field)
                if field_value:
                    match = self._find_matches(field, field_value, terms)
                    if match:
                        matches.append(match)

            if matches:
                # Calculate overall score
                score = self._calculate_score(matches)
                results.append(SearchResult(
                    task=task,
                    matches=matches,
                    overall_score=score,
                    search_type=SearchType.TEXT,
                ))

        return results

    async def _semantic_search(
        self,
        tasks: list[Task],
        criteria: SearchCriteria,
    ) -> list[SearchResult]:
        """Perform semantic search using vector embeddings."""
        # Placeholder for semantic search implementation
        # Would use self.vector_search to find similar tasks
        # For now, fall back to text search
        return await self._text_search(tasks, criteria)

    async def _hybrid_search(
        self,
        tasks: list[Task],
        criteria: SearchCriteria,
    ) -> list[SearchResult]:
        """Perform hybrid search combining text and semantic."""
        # Get results from both methods
        text_results = await self._text_search(tasks, criteria)
        semantic_results = await self._semantic_search(tasks, criteria)

        # Merge and re-rank
        merged: dict[str, SearchResult] = {}

        for result in text_results:
            merged[result.task.id] = SearchResult(
                task=result.task,
                matches=result.matches,
                overall_score=result.overall_score * 0.5,  # Weight for text
                search_type=SearchType.HYBRID,
            )

        for result in semantic_results:
            if result.task.id in merged:
                # Combine scores
                merged[result.task.id].overall_score += result.overall_score * 0.5
            else:
                merged[result.task.id] = SearchResult(
                    task=result.task,
                    matches=result.matches,
                    overall_score=result.overall_score * 0.5,  # Weight for semantic
                    search_type=SearchType.HYBRID,
                )

        return list(merged.values())

    def _parse_query(self, query: str) -> list[str]:
        """Parse query into search terms."""
        # Simple tokenization - split on whitespace and remove punctuation
        terms = re.findall(r'\b\w+\b', query.lower())
        return [t for t in terms if len(t) >= 2]  # Ignore very short terms

    def _get_field_value(self, task: Task, field: str) -> str:
        """Get the string value of a task field."""
        if field == "title":
            return task.title or ""
        elif field == "description":
            return task.description or ""
        elif field == "tags":
            return " ".join(task.tags) if task.tags else ""
        else:
            return str(getattr(task, field, ""))

    def _find_matches(
        self,
        field: str,
        value: str,
        terms: list[str],
    ) -> SearchMatch | None:
        """Find matching terms in a field value."""
        value_lower = value.lower()
        matches_positions: list[tuple[int, int]] = []
        matched_terms: set[str] = set()

        for term in terms:
            # Find all occurrences
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            for match in pattern.finditer(value):
                matches_positions.append((match.start(), match.end()))
                matched_terms.add(term)

        if not matches_positions:
            return None

        # Create highlighted snippet
        snippet = self._create_snippet(value, matches_positions)

        # Calculate match score
        coverage = len(matched_terms) / len(terms) if terms else 0
        density = len(matches_positions) / max(1, len(value.split()))
        score = min(1.0, (coverage * 0.7 + density * 0.3))

        return SearchMatch(
            field=field,
            snippet=snippet,
            score=score,
            positions=matches_positions,
        )

    def _create_snippet(
        self,
        value: str,
        positions: list[tuple[int, int]],
        max_length: int = 100,
    ) -> str:
        """Create a snippet with matches highlighted."""
        if not positions:
            return value[:max_length]

        # Sort positions by start
        sorted_positions = sorted(positions, key=lambda p: p[0])

        # Find the best region to show
        first_match = sorted_positions[0][0]
        start = max(0, first_match - 30)
        end = min(len(value), start + max_length)

        snippet = value[start:end]

        # Add ellipsis if truncated
        if start > 0:
            snippet = "..." + snippet
        if end < len(value):
            snippet = snippet + "..."

        # Highlight matches (adjust positions for snippet start)
        highlighted = snippet
        offset = start if start > 0 else 0

        # Collect terms to highlight
        terms_to_highlight = set()
        for s, e in sorted_positions:
            if s >= start and e <= end:
                term = value[s:e]
                terms_to_highlight.add(term.lower())

        # Apply highlighting
        for term in terms_to_highlight:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            highlighted = pattern.sub(f"**{term}**", highlighted)

        return highlighted

    def _calculate_score(self, matches: list[SearchMatch]) -> float:
        """Calculate overall score from field matches."""
        if not matches:
            return 0.0

        weighted_sum = 0.0
        total_weight = 0.0

        for match in matches:
            weight = self.FIELD_WEIGHTS.get(match.field, 1.0)
            weighted_sum += match.score * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _apply_filters(
        self,
        results: list[SearchResult],
        criteria: SearchCriteria,
    ) -> list[SearchResult]:
        """Apply post-search filters to results."""
        filtered = results

        # Filter by repository
        if criteria.repo_names:
            filtered = [
                r for r in filtered
                if r.task.repository in criteria.repo_names
            ]

        # Filter by status (if multiple)
        if criteria.statuses:
            filtered = [
                r for r in filtered
                if r.task.status in criteria.statuses
            ]

        # Filter by priority (if multiple)
        if criteria.priorities:
            filtered = [
                r for r in filtered
                if r.task.priority in criteria.priorities
            ]

        # Filter by tags (ANY match)
        if criteria.tags:
            filtered = [
                r for r in filtered
                if any(tag in r.task.tags for tag in criteria.tags)
            ]

        return filtered

    async def suggest_completions(self, partial: str, limit: int = 10) -> list[str]:
        """Suggest query completions based on task data.

        Args:
            partial: Partial query string
            limit: Maximum suggestions to return

        Returns:
            List of suggested completions
        """
        tasks = await self.task_store.list(TaskListFilter(limit=1000))

        # Collect all words from titles and tags
        words: set[str] = set()
        for task in tasks:
            # Add title words
            words.update(w.lower() for w in task.title.split() if len(w) >= 3)
            # Add tags
            words.update(t.lower() for t in task.tags)

        # Find words that start with partial
        partial_lower = partial.lower()
        matches = [w for w in words if w.startswith(partial_lower)]

        # Sort by length (shorter = better suggestion)
        matches.sort()

        return matches[:limit]


__all__ = [
    "CrossRepoSearch",
    "SearchCriteria",
    "SearchResult",
    "SearchMatch",
    "SearchType",
]
