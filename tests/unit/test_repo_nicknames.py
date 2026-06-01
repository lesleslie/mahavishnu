"""Tests for repository nickname normalization helpers."""

from __future__ import annotations

from mahavishnu.core.repo_nicknames import get_repo_nicknames, normalize_nicknames


class TestNormalizeNicknames:
    def test_normalizes_strings_and_preserves_order(self) -> None:
        result = normalize_nicknames(
            nickname="  main  ",
            nicknames=["feature", "main", "  ops  ", ""],
        )

        assert result == ["main", "feature", "ops"]

    def test_accepts_single_string_alias(self) -> None:
        result = normalize_nicknames(nicknames="  shared  ")

        assert result == ["shared"]

    def test_ignores_blank_values(self) -> None:
        result = normalize_nicknames(nickname="   ", nicknames=["", "  "])

        assert result == []


class TestGetRepoNicknames:
    def test_extracts_and_normalizes_values(self) -> None:
        repo = {
            "nickname": "  primary ",
            "nicknames": ["primary", "alt", "  backup  "],
        }

        assert get_repo_nicknames(repo) == ["primary", "alt", "backup"]

    def test_handles_missing_keys(self) -> None:
        assert get_repo_nicknames({}) == []
