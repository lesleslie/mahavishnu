from __future__ import annotations

import re

from mahavishnu.jot.redact import REDACTED_PATTERN, redact_text


class TestTier1Secrets:
    def test_aws_access_key_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("aws_key=AKIAIOSFODNN7EXAMPLE")

    def test_github_pat_ghp_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789")

    def test_openai_key_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ")

    def test_anthropic_key_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("sk-ant-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123")

    def test_slack_xoxb_token_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("xoxb-12345-aBcDeFgHiJkLmNoPqRsTuVwX")

    def test_jwt_redacted(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature_here_aaa"
        assert "[REDACTED:secret:" in redact_text(jwt)

    def test_bearer_token_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("Authorization: Bearer abc123_def-456.ghi")

    def test_secrets_are_not_destroyed_around_match(self) -> None:
        """Redaction must preserve surrounding text."""
        result = redact_text("prefix AKIAIOSFODNN7EXAMPLE suffix")
        assert result.startswith("prefix ")
        assert result.endswith(" suffix")
        assert "[REDACTED:secret:" in result


class TestTier2Credentials:
    def test_email_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("contact: alice@example.com")

    def test_us_phone_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("call 555-123-4567 today")

    def test_us_phone_no_dashes_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("call 5551234567 today")

    def test_ipv4_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("server at 192.168.1.1")

    def test_credentials_preserve_surrounding_text(self) -> None:
        result = redact_text("server 10.0.0.1 alive")
        assert "server " in result
        assert "alive" in result


class TestTier3UrlsEnvStyle:
    def test_https_url_redacted(self) -> None:
        assert "[REDACTED:url:" in redact_text("visit https://example.com/path?q=1")

    def test_http_url_redacted(self) -> None:
        assert "[REDACTED:url:" in redact_text("see http://internal.corp/page")

    def test_env_reference_redacted(self) -> None:
        assert "[REDACTED:env:" in redact_text("check the .env file")

    def test_env_local_reference_redacted(self) -> None:
        assert "[REDACTED:env:" in redact_text("see .env.local for secrets")

    def test_ssh_private_key_header_redacted(self) -> None:
        text = "-----BEGIN RSA PRIVATE KEY-----"
        assert "[REDACTED:env:" in redact_text(text)


class TestNegativeCases:
    def test_plain_text_unchanged(self) -> None:
        text = "refactor the fold function to use HLC ordering"
        assert redact_text(text) == text

    def test_short_strings_not_redacted(self) -> None:
        text = "AKIA123"
        assert text in redact_text(text)

    def test_no_redaction_for_safe_words(self) -> None:
        text = "the quick brown fox jumps over the lazy dog"
        assert redact_text(text) == text

    def test_empty_string_returns_empty(self) -> None:
        assert redact_text("") == ""

    def test_hash_consistency_same_secret_same_hash(self) -> None:
        """Same secret produces same redacted hash (for correlation)."""
        secret = "AKIAIOSFODNN7EXAMPLE"
        r1 = redact_text(secret)
        r2 = redact_text(secret)
        assert r1 == r2

    def test_hash_different_for_different_secrets(self) -> None:
        """Different secrets produce different redacted hashes."""
        r1 = redact_text("AKIAIOSFODNN7EXAMPLE")
        r2 = redact_text("AKIAIOSFODNN7DIFFERN")
        m1 = re.search(r"\[REDACTED:[^:]+:([0-9a-f]+)\]", r1)
        m2 = re.search(r"\[REDACTED:[^:]+:([0-9a-f]+)\]", r2)
        assert m1 and m2
        assert m1.group(1) != m2.group(1)


def test_redacted_pattern_exported() -> None:
    """The REDACTED_PATTERN regex must be importable for sub-plan 2's read surface."""
    assert re.match(REDACTED_PATTERN, "[REDACTED:secret:abcdef01]")


def test_redact_text_idempotent() -> None:
    """Redacting already-redacted text must not double-redact."""
    text = "AKIAIOSFODNN7EXAMPLE"
    once = redact_text(text)
    twice = redact_text(once)
    assert once == twice
