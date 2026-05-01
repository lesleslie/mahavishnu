"""Fuzzy search algorithms for skill discovery."""

from typing import List
from dataclasses import dataclass, field

from skill_finder.indexer import SearchIndex


@dataclass
class SearchResult:
    """Search result with relevance score."""
    skill_name: str
    score: float
    match_type: str  # "exact", "keyword", "description", "symptom"
    matched_terms: List[str] = field(default_factory=list)

    def __lt__(self, other):
        """Sort by score descending."""
        return self.score > other.score


def fuzzy_search(query: str, index: SearchIndex, limit: int = 5) -> List[SearchResult]:
    """
    Fuzzy search across skill names, descriptions, keywords, and symptoms.

    Args:
        query: Search query string
        index: SearchIndex to search
        limit: Maximum number of results

    Returns:
        List of SearchResult sorted by relevance
    """
    query_lower = query.lower()
    results = []

    # 1. Exact name match (100%)
    for skill_name in index.skills:
        if query_lower == skill_name.lower():
            results.append(SearchResult(
                skill_name=skill_name,
                score=1.0,
                match_type="exact",
                matched_terms=[query]
            ))
            return results[:limit]  # Exact match returns immediately

    # 2. Keyword matches (80-95%)
    for keyword, skill_names in index.keyword_index.items():
        if query_lower in keyword:
            for skill_name in skill_names:
                score = 0.95 if query_lower == keyword else 0.85
                results.append(SearchResult(
                    skill_name=skill_name,
                    score=score,
                    match_type="keyword",
                    matched_terms=[keyword]
                ))

    # 3. Symptom matches (70-90%)
    for symptom, skill_names in index.symptom_index.items():
        if query_lower in symptom:
            for skill_name in skill_names:
                score = 0.90 if query_lower == symptom else 0.75
                results.append(SearchResult(
                    skill_name=skill_name,
                    score=score,
                    match_type="symptom",
                    matched_terms=[symptom]
                ))

    # 4. Description matches (60-80%)
    for skill_name, skill in index.skills.items():
        if query_lower in skill.description.lower():
            # Calculate score based on position and occurrence count
            description_lower = skill.description.lower()
            occurrences = description_lower.count(query_lower)
            position = description_lower.find(query_lower)
            score = 0.80 - (position / len(description_lower)) * 0.1 + (occurrences * 0.05)
            results.append(SearchResult(
                skill_name=skill_name,
                score=score,
                match_type="description",
                matched_terms=[query]
            ))

    # 5. Skill name substring match (70-85%)
    for skill_name in index.skills:
        if query_lower in skill_name.lower() and query_lower != skill_name.lower():
            score = 0.85 if skill_name.lower().startswith(query_lower) else 0.75
            results.append(SearchResult(
                skill_name=skill_name,
                score=score,
                match_type="name_substring",
                matched_terms=[skill_name]
            ))

    # Remove duplicates (keep highest score)
    unique_results = {}
    for result in results:
        if result.skill_name not in unique_results or result.score > unique_results[result.skill_name].score:
            unique_results[result.skill_name] = result

    # Sort by score descending
    sorted_results = sorted(unique_results.values(), key=lambda r: r.score, reverse=True)

    return sorted_results[:limit]


def exact_search(query: str, index: SearchIndex) -> List[str]:
    """
    Exact match search by skill name.

    Args:
        query: Exact skill name to search for
        index: SearchIndex to search

    Returns:
        List of matching skill names (0 or 1)
    """
    query_lower = query.lower()
    matches = []

    for skill_name in index.skills:
        if query_lower == skill_name.lower():
            matches.append(skill_name)

    return matches


def search_by_system(system: str, index: SearchIndex) -> List[str]:
    """
    Get all skills for a specific system.

    Args:
        system: System name (e.g., "mahavishnu", "oneiric")
        index: SearchIndex to search

    Returns:
        List of skill names in the system
    """
    return index.system_index.get(system, [])


def search_by_keyword(keyword: str, index: SearchIndex) -> List[str]:
    """
    Get all skills that match a keyword.

    Args:
        keyword: Keyword to search for
        index: SearchIndex to search

    Returns:
        List of skill names with the keyword
    """
    keyword_lower = keyword.lower()
    matches = []

    for kw, skill_names in index.keyword_index.items():
        if keyword_lower in kw:
            matches.extend(skill_names)

    return list(set(matches))  # Remove duplicates
