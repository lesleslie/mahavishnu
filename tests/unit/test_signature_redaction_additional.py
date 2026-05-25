"""Additional tests for signature redaction helpers."""

from __future__ import annotations

from mahavishnu.core.code_index.signature_redaction import (
    has_secrets,
    redact_signature,
)


def test_redact_signature_leaves_current_broad_patterns_unchanged():
    signature = 'config: str = os.environ["API_TOKEN"]'

    assert redact_signature(signature) == signature
    assert has_secrets(signature) is False


def test_redact_signature_leaves_current_f_string_pattern_unchanged():
    signature = 'f"token={value} -> {result}"'

    assert redact_signature(signature) == signature
    assert has_secrets(signature) is False


def test_redact_signature_none_and_has_secrets_none():
    assert redact_signature(None) == ""
    assert has_secrets(None) is False
