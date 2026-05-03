"""Helpers for normalizing repository nickname aliases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def normalize_nicknames(
    nickname: str | None = None,
    nicknames: str | Iterable[str] | None = None,
) -> list[str]:
    """Return a deduplicated nickname list preserving input order."""
    values: list[str] = []

    if isinstance(nickname, str) and nickname.strip():
        values.append(nickname.strip())

    if isinstance(nicknames, str):
        candidate_values = [nicknames]
    elif nicknames is None:
        candidate_values = []
    else:
        candidate_values = list(nicknames)

    for candidate in candidate_values:
        if isinstance(candidate, str) and candidate.strip():
            values.append(candidate.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)

    return deduped


def get_repo_nicknames(repo: Mapping[str, Any]) -> list[str]:
    """Extract normalized nicknames from a repository config mapping."""
    return normalize_nicknames(repo.get("nickname"), repo.get("nicknames"))
