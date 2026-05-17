"""Tests for signature redaction."""

import pytest

from mahavishnu.core.code_index.signature_redaction import (
    has_secrets,
    redact_signature,
)


def test_redact_api_key():
    assert (
        redact_signature('def connect(api_key="sk-abc123")') == 'def connect(api_key="<REDACTED>")'
    )


def test_redact_password():
    assert redact_signature('password = "hunter2"') == 'password = "<REDACTED>"'


def test_redact_bearer_token():
    assert redact_signature('token = "ghp_xxxxxxxxxxxx"') == 'token = "<REDACTED>"'


def test_no_redaction_clean_signature():
    sig = "def process_data(items: list[str], limit: int = 10) -> None:"
    assert redact_signature(sig) == sig


def test_has_secrets_true():
    assert has_secrets('def connect(api_key="sk-abc123")') is True


def test_has_secrets_false():
    assert has_secrets("def hello(name: str) -> None:") is False


def test_redact_none():
    assert redact_signature(None) == ""


def test_redact_connection_string():
    assert redact_signature('database_url = "postgres://..."') == 'database_url = "<REDACTED>"'


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        ('api_secret = "abc"', 'api_secret = "<REDACTED>"'),
        ('private_key = "-----BEGIN RSA PRIVATE KEY-----"', 'private_key = "<REDACTED>"'),
        ('github_token = "ghp_123"', 'github_token = "<REDACTED>"'),
    ],
)
def test_redact_additional_secret_patterns(signature: str, expected: str) -> None:
    assert redact_signature(signature) == expected


def test_has_secrets_none() -> None:
    assert has_secrets(None) is False


@pytest.mark.parametrize(
    "signature",
    [
        'api_secret = "abc"',
        'private_key = "-----BEGIN RSA PRIVATE KEY-----"',
        'github_token = "ghp_123"',
    ],
)
def test_has_secrets_additional_matches(signature: str) -> None:
    assert has_secrets(signature) is True
