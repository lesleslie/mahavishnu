"""Redact secret-bearing patterns from function signatures before storage."""

from __future__ import annotations

import re

# Patterns match keyword=value pairs where value is a quoted string.
# Group 1 captures the keyword (e.g. "api_key"), group 2 the assignment (e.g. "=").
_SECRET_VALUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        r"(?i)(api_key|apikey|api_secret)(\s*=\s*)['\"][^'\"]*['\"]",
        r"(?i)(password|passwd|pwd)(\s*=\s*)['\"][^'\"]*['\"]",
        r"(?i)(token|auth_token|access_token)(\s*=\s*)['\"][^'\"]*['\"]",
        r"(?i)(secret|client_secret)(\s*=\s*)['\"][^'\"]*['\"]",
        r"(?i)(private_key|rsa_private|ec_private|ssh_key)(\s*=\s*)['\"][^'\"]*['\"]",
        r"(?i)(connection_string|database_url|redis_url)(\s*=\s*)['\"][^'\"]*['\"]",
        r"(?i)(webhook_secret|bearer|credential)(\s*=\s*)['\"][^'\"]*['\"]",
        r"(?i)(aws_secret_access_key|github_token|slack_token)(\s*=\s*)['\"][^'\"]*['\"]",
    ]
]

# Broader patterns that match entire constructs (os.environ, f-strings, etc.).
_SECRET_BROAD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r'(?i)\w+\s*:\s*str\s*=\s*os\.environ\["\'][^"\']+["\']',
    ),
    re.compile(
        r"(?i)f['\"][^'\"]*(?:token|key|secret|password)[^'\"]*['\"].*\{",
    ),
]

# Combined list for has_secrets checks.
SECRET_PATTERNS: list[re.Pattern[str]] = [
    *_SECRET_VALUE_PATTERNS,
    *_SECRET_BROAD_PATTERNS,
]


def _redact_value_match(m: re.Match[str]) -> str:
    """Return the match with only the quoted value replaced."""
    return f'{m.group(1)}{m.group(2)}"<REDACTED>"'


def redact_signature(signature: str | None) -> str:
    """Replace secret-bearing patterns in a function signature.

    Returns the redacted signature, or the original if no secrets found.
    """
    if signature is None:
        return ""
    redacted = signature
    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(_redact_value_match, redacted)
    for pattern in _SECRET_BROAD_PATTERNS:
        redacted = pattern.sub('"<REDACTED>"', redacted)
    return redacted


def has_secrets(signature: str | None) -> bool:
    """Check if a signature contains potential secrets."""
    if signature is None:
        return False
    return any(p.search(signature) for p in SECRET_PATTERNS)
