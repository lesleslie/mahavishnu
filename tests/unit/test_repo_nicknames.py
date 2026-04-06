"""Tests for repository nickname normalization.

Tests cover:
- normalize_nicknames with various input combinations
- get_repo_nicknames extraction from config mappings
- Edge cases: whitespace, empty strings, duplicates, order preservation
"""

import pytest

from mahavishnu.core.repo_nicknames import get_repo_nicknames, normalize_nicknames


# ============================================================================
# normalize_nicknames Tests
# ============================================================================


class TestNormalizeNicknamesBasic:
    """Test basic normalize_nicknames behavior."""

    def test_none_inputs(self):
        assert normalize_nicknames() == []

    def test_single_nickname(self):
        result = normalize_nicknames(nickname="myrepo")
        assert result == ["myrepo"]

    def test_single_nicknames_string(self):
        result = normalize_nicknames(nicknames="myrepo")
        assert result == ["myrepo"]

    def test_nicknames_list(self):
        result = normalize_nicknames(nicknames=["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_both_nickname_and_nicknames(self):
        result = normalize_nicknames(nickname="primary", nicknames=["alt1", "alt2"])
        assert result == ["primary", "alt1", "alt2"]


class TestNormalizeNicknamesDeduplication:
    """Test deduplication behavior."""

    def test_deduplicates_identical_values(self):
        result = normalize_nicknames(nickname="repo", nicknames=["repo", "other"])
        assert result == ["repo", "other"]

    def test_deduplicates_within_list(self):
        result = normalize_nicknames(nicknames=["a", "b", "a", "c", "b"])
        assert result == ["a", "b", "c"]

    def test_deduplicates_across_nickname_and_list(self):
        result = normalize_nicknames(nickname="x", nicknames=["x", "y", "x"])
        assert result == ["x", "y"]


class TestNormalizeNicknamesWhitespace:
    """Test whitespace handling."""

    def test_strips_nickname_whitespace(self):
        result = normalize_nicknames(nickname="  myrepo  ")
        assert result == ["myrepo"]

    def test_strips_nicknames_whitespace(self):
        result = normalize_nicknames(nicknames=["  a  ", " b ", "c"])
        assert result == ["a", "b", "c"]

    def test_skips_empty_after_strip(self):
        result = normalize_nicknames(nickname="   ", nicknames=["", "  ", "valid"])
        assert result == ["valid"]

    def test_empty_string_nickname_skipped(self):
        result = normalize_nicknames(nickname="")
        assert result == []

    def test_whitespace_only_nickname_skipped(self):
        result = normalize_nicknames(nickname="   ")
        assert result == []


class TestNormalizeNicknamesOrderPreservation:
    """Test that order is preserved."""

    def test_preserves_input_order(self):
        result = normalize_nicknames(nicknames=["z", "a", "m", "b"])
        assert result == ["z", "a", "m", "b"]

    def test_nickname_comes_before_nicknames(self):
        result = normalize_nicknames(nickname="first", nicknames=["second", "third"])
        assert result == ["first", "second", "third"]

    def test_first_occurrence_kept_on_duplicate(self):
        result = normalize_nicknames(nicknames=["alpha", "beta", "alpha"])
        assert result == ["alpha", "beta"]
        assert len(result) == 2


class TestNormalizeNicknamesEdgeCases:
    """Test edge cases."""

    def test_empty_nicknames_list(self):
        result = normalize_nicknames(nicknames=[])
        assert result == []

    def test_tuple_nicknames(self):
        result = normalize_nicknames(nicknames=("a", "b"))
        assert result == ["a", "b"]

    def test_non_string_in_list_ignored(self):
        result = normalize_nicknames(nicknames=["a", 123, "b"])
        # Non-string items are skipped (isinstance check)
        assert result == ["a", "b"]

    def test_single_character_nickname(self):
        result = normalize_nicknames(nickname="x")
        assert result == ["x"]


# ============================================================================
# get_repo_nicknames Tests
# ============================================================================


class TestGetRepoNicknames:
    """Test get_repo_nicknames extraction from config."""

    def test_empty_mapping(self):
        assert get_repo_nicknames({}) == []

    def test_with_nickname_only(self):
        result = get_repo_nicknames({"nickname": "vishnu"})
        assert result == ["vishnu"]

    def test_with_nicknames_only(self):
        result = get_repo_nicknames({"nicknames": ["a", "b"]})
        assert result == ["a", "b"]

    def test_with_both(self):
        result = get_repo_nicknames({
            "nickname": "primary",
            "nicknames": ["alt1", "alt2"],
        })
        assert result == ["primary", "alt1", "alt2"]

    def test_with_none_values(self):
        result = get_repo_nicknames({"nickname": None, "nicknames": None})
        assert result == []

    def test_deduplicates_from_config(self):
        result = get_repo_nicknames({
            "nickname": "repo",
            "nicknames": ["repo", "other"],
        })
        assert result == ["repo", "other"]

    def test_extra_keys_ignored(self):
        result = get_repo_nicknames({
            "name": "mahavishnu",
            "path": "/some/path",
            "nickname": "vishnu",
        })
        assert result == ["vishnu"]
