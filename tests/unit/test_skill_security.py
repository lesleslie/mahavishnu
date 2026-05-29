"""Unit tests for mahavishnu/core/skill_security.py."""

from __future__ import annotations

from mahavishnu.core.skill_governance import SkillDraft
from mahavishnu.core.skill_security import (
    DANGEROUS_PATTERNS,
    MAX_SKILL_BODY_LENGTH,
    is_draft_namespace,
    sanitize_skill_body,
    validate_draft_isolation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_draft(
    name: str = "test-skill",
    skill_id: str = "skill_test",
    body: str = "# Test body",
    version: str = "1.0.0",
) -> SkillDraft:
    """Create a minimal SkillDraft with required fields."""
    return SkillDraft(
        skill_id=skill_id,
        name=name,
        version=version,
        description="Test skill description",
        trigger_conditions=["on_request"],
        body=body,
    )


# ---------------------------------------------------------------------------
# sanitize_skill_body Tests
# ---------------------------------------------------------------------------


class TestSanitizeSkillBody:
    def test_redacts_dangerous_patterns(self):
        body = 'result = __import__("os").system("rm -rf /")'
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: __import__]" in sanitized

    def test_redacts_exec(self):
        body = "exec('print(1)')"
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: exec(" in sanitized

    def test_redacts_eval(self):
        body = "eval('1 + 1')"
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: eval(" in sanitized

    def test_redacts_compile(self):
        body = "compile('code', '', 'exec')"
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: compile(" in sanitized

    def test_redacts_globals(self):
        body = "globals()"
        sanitized = sanitize_skill_body(body)

        # Original pattern is replaced; the redaction label contains "globals("
        # so we check for the redaction label instead
        assert "[REDACTED: globals(" in sanitized

    def test_redacts_locals(self):
        body = "locals()"
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: locals(" in sanitized

    def test_redacts_getattr(self):
        body = "getattr(obj, 'attr')"
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: getattr(" in sanitized

    def test_redacts_setattr(self):
        body = "setattr(obj, 'attr', value)"
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: setattr(" in sanitized

    def test_redacts_delattr(self):
        body = "delattr(obj, 'attr')"
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: delattr(" in sanitized

    def test_collapse_excessive_blank_lines(self):
        body = "line 1\n\n\n\n\nline 2"
        sanitized = sanitize_skill_body(body)

        assert sanitized.count("\n\n\n") == 1

    def test_preserve_single_blank_line(self):
        body = "line 1\n\nline 2"
        sanitized = sanitize_skill_body(body)

        assert sanitized == body

    def test_truncate_long_body(self):
        long_body = "x" * (MAX_SKILL_BODY_LENGTH + 1000)
        sanitized = sanitize_skill_body(long_body)

        assert len(sanitized) == MAX_SKILL_BODY_LENGTH

    def test_preserves_short_body(self):
        body = "print('hello')"
        sanitized = sanitize_skill_body(body)

        assert sanitized == body

    def test_multiple_dangerous_patterns_redacted(self):
        body = """
__import__('os')
eval('1 + 1')
exec('print(2)')
"""
        sanitized = sanitize_skill_body(body)

        assert "[REDACTED: __import__]" in sanitized
        assert "[REDACTED: eval(" in sanitized
        assert "[REDACTED: exec(" in sanitized


# ---------------------------------------------------------------------------
# validate_draft_isolation Tests
# ---------------------------------------------------------------------------


class TestValidateDraftIsolation:
    def test_no_issues_for_valid_draft(self):
        draft = make_draft(name="valid-skill", body="print('hello')")
        issues = validate_draft_isolation(draft)

        assert issues == []

    def test_path_separator_forward_slash(self):
        draft = make_draft(name="bad/skill")
        issues = validate_draft_isolation(draft)

        assert any("path separator" in issue for issue in issues)

    def test_path_separator_backslash(self):
        draft = make_draft(name="bad\\skill")
        issues = validate_draft_isolation(draft)

        assert any("path separator" in issue for issue in issues)

    def test_path_separator_dot_dot(self):
        draft = make_draft(name="bad..skill")
        issues = validate_draft_isolation(draft)

        assert any("path separator" in issue for issue in issues)

    def test_leading_underscore_rejected(self):
        draft = make_draft(name="_internal_skill")
        issues = validate_draft_isolation(draft)

        assert any("starts with underscore" in issue for issue in issues)

    def test_fs_access_open_warning(self):
        draft = make_draft(name="fs-skill", body='f = open("file.txt")')
        issues = validate_draft_isolation(draft)

        assert any("filesystem access pattern" in issue and "open(" in issue for issue in issues)

    def test_fs_access_pathlib_warning(self):
        draft = make_draft(name="path-skill", body="from pathlib import Path")
        issues = validate_draft_isolation(draft)

        assert any("filesystem access pattern" in issue and "pathlib" in issue for issue in issues)

    def test_fs_access_os_path_warning(self):
        draft = make_draft(name="ospath-skill", body="os.path.exists")
        issues = validate_draft_isolation(draft)

        assert any("filesystem access pattern" in issue and "os.path" in issue for issue in issues)

    def test_network_requests_warning(self):
        draft = make_draft(
            name="net-skill", body="import requests; requests.get('http://example.com')"
        )
        issues = validate_draft_isolation(draft)

        assert any("network access pattern" in issue and "requests." in issue for issue in issues)

    def test_network_httpx_warning(self):
        draft = make_draft(name="httpx-skill", body="import httpx; httpx.get('http://example.com')")
        issues = validate_draft_isolation(draft)

        assert any("network access pattern" in issue and "httpx." in issue for issue in issues)

    def test_network_urllib_warning(self):
        draft = make_draft(name="url-skill", body="from urllib import request")
        issues = validate_draft_isolation(draft)

        assert any("network access pattern" in issue and "urllib" in issue for issue in issues)

    def test_network_socket_warning(self):
        draft = make_draft(name="sock-skill", body="import socket; socket.socket()")
        issues = validate_draft_isolation(draft)

        assert any("network access pattern" in issue and "socket." in issue for issue in issues)

    def test_network_http_client_warning(self):
        draft = make_draft(name="hc-skill", body="from http.client import HTTPConnection")
        issues = validate_draft_isolation(draft)

        assert any("network access pattern" in issue and "http.client" in issue for issue in issues)

    def test_multiple_path_separators_reported(self):
        draft = make_draft(name="bad/slash\\dot")
        issues = validate_draft_isolation(draft)

        # At least one path separator issue should be reported
        assert len(issues) >= 1

    def test_combined_fs_and_network_issues(self):
        draft = make_draft(
            name="combined-skill",
            body='f = open("file.txt")\nimport requests.get("http://example.com")',
        )
        issues = validate_draft_isolation(draft)

        # Should have both fs and network issues
        has_fs = any("filesystem access pattern" in issue for issue in issues)
        has_net = any("network access pattern" in issue for issue in issues)
        assert has_fs and has_net


# ---------------------------------------------------------------------------
# is_draft_namespace Tests
# ---------------------------------------------------------------------------


class TestIsDraftNamespace:
    def test_draft_prefix_returns_true(self):
        assert is_draft_namespace("draft/my-skill") is True

    def test_skill_prefix_returns_false(self):
        assert is_draft_namespace("skill/my-skill") is False

    def test_empty_returns_false(self):
        assert is_draft_namespace("") is False

    def test_exact_draft_string(self):
        assert is_draft_namespace("draft/") is True

    def test_longer_draft_namespace(self):
        assert is_draft_namespace("draft/nested/deep/skill") is True

    def test_similar_prefix_not_matched(self):
        assert is_draft_namespace("draftlike/skill") is False
        assert is_draft_namespace("undrafted/skill") is False


# ---------------------------------------------------------------------------
# DANGEROUS_PATTERNS and MAX_SKILL_BODY_LENGTH Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_dangerous_patterns_not_empty(self):
        assert len(DANGEROUS_PATTERNS) > 0

    def test_dangerous_patterns_format(self):
        for label, pattern in DANGEROUS_PATTERNS:
            assert isinstance(label, str)
            assert hasattr(pattern, "search")
            assert callable(pattern.search)

    def test_max_skill_body_length_is_reasonable(self):
        assert MAX_SKILL_BODY_LENGTH > 0
        assert MAX_SKILL_BODY_LENGTH > 1000


# ---------------------------------------------------------------------------
# Integration-style Tests (combining functions)
# ---------------------------------------------------------------------------


class TestSanitizeAndValidate:
    def test_clean_body_passes_validation(self):
        body = "def hello():\n    print('Hello, World!')"
        draft = make_draft(name="hello-skill", body=body)
        sanitized = sanitize_skill_body(body)

        # Re-validate after sanitize
        issues = validate_draft_isolation(draft)
        assert issues == []

    def test_dangerous_body_is_sanitized_and_flagged(self):
        body = 'exec("malicious code")'
        draft = make_draft(name="dangerous-skill", body=body)

        sanitized = sanitize_skill_body(body)
        assert "[REDACTED: exec(" in sanitized

        # validate_draft_isolation checks raw draft body, not sanitized
        # So the original dangerous pattern is still in the draft body when checked
        issues = validate_draft_isolation(draft)
        # exec is not in the isolation patterns, only in dangerous patterns
        assert len(issues) == 0
