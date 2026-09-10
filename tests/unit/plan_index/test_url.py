from __future__ import annotations

import pytest

from mahavishnu.plan_index.url import (
    RepoUrlRejectedError,
    normalize_repo_url,
)


class TestNormalizeSshForm:
    def test_ssh_shorthand_normalized(self) -> None:
        result = normalize_repo_url("git@github.com:foo/bar.git")
        assert result is not None
        # Userinfo stripped, host lowercased, path hashed
        assert "github.com" in result
        assert "@" not in result.split("/")[0]  # no userinfo in path segment
        assert result.startswith("github.com/")


class TestNormalizeHttpsForm:
    def test_https_normalized(self) -> None:
        result = normalize_repo_url("https://github.com/foo/bar.git")
        assert result is not None
        assert "github.com" in result


class TestNormalizeSshProtocolForm:
    def test_ssh_protocol_normalized(self) -> None:
        result = normalize_repo_url("ssh://git@github.com/foo/bar.git")
        assert result is not None
        assert "github.com" in result


class TestThreeUrlFormsSameRepo:
    def test_three_forms_produce_same_normalization(self) -> None:
        forms = [
            "git@github.com:foo/bar.git",
            "https://github.com/foo/bar.git",
            "ssh://git@github.com/foo/bar.git",
        ]
        normalized = [normalize_repo_url(f) for f in forms]
        assert all(n is not None for n in normalized)
        # Same host + same path → same normalized output
        # (path normalization hashes path segments so two forms with same path produce same)
        assert normalized[0] == normalized[1] == normalized[2]


class TestRejection:
    def test_empty_string_rejected(self) -> None:
        assert normalize_repo_url("") is None

    def test_garbage_string_rejected(self) -> None:
        assert normalize_repo_url("not a url") is None

    def test_control_characters_rejected(self) -> None:
        with pytest.raises(Exception):
            normalize_repo_url("git@github.com:foo/bar\x00.git")

    def test_ftp_protocol_rejected(self) -> None:
        assert normalize_repo_url("ftp://github.com/foo/bar.git") is None


class TestUserinfoStripping:
    def test_https_with_userinfo_strips_user(self) -> None:
        result = normalize_repo_url("https://user:pass@github.com/foo/bar.git")
        assert result is not None
        # No "user" or "pass" in normalized form
        assert "user" not in result
        assert "pass" not in result

    def test_ssh_user_prefix_stripped(self) -> None:
        result = normalize_repo_url("git@github.com:foo/bar.git")
        assert result is not None
        # The "git@" user is stripped
        assert not result.startswith("git@")


class TestHostLowercasing:
    def test_uppercase_host_lowercased(self) -> None:
        result = normalize_repo_url("https://GitHub.com/foo/bar.git")
        assert result is not None
        assert "github.com" in result
        assert "GitHub.com" not in result


class TestPathHashing:
    def test_path_segments_hashed(self) -> None:
        result = normalize_repo_url("https://github.com/secret-org/secret-project.git")
        assert result is not None
        # Path segments should NOT appear verbatim in normalized form
        assert "secret-org" not in result
        assert "secret-project" not in result


class TestRepoUrlRejectedError:
    def test_raised_with_rejection_reason(self) -> None:
        with pytest.raises(RepoUrlRejectedError) as exc_info:
            normalize_repo_url("garbage", raise_on_reject=True)
        assert exc_info.value.reason  # populated
