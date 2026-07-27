"""Safe-redaction helpers for capability reports, exceptions, and logs."""

from __future__ import annotations

import re
from typing import Any

# Broader credential-shape pattern than the original sk-/ghp_-only set.
# The pattern is case-insensitive and matches:
#   sk-[A-Za-z0-9_-]{8,}    OpenAI / Anthropic / generic "sk-" keys (hyphens allowed)
#   ghp_[a-z0-9]{8,}        GitHub personal access tokens
#   xox[ab]-[a-z0-9-]{8,}   Slack app/bot tokens
#   ya29.[a-z0-9_-]{4,}     Google OAuth refresh tokens
#   eyJ[A-Za-z0-9_-]{16,}   JWTs (base64url-decoded "{", base payload header)
#   AKIA[0-9A-Z]{16}        AWS access key IDs
#   glpat-[A-Za-z0-9_-]{16,} GitLab personal access tokens
#   bearer\s+[a-z0-9._-]{8,} Authorization: Bearer <token>
_SECRET_PATTERN = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{8,}|ghp_[a-z0-9]{8,}|xox[ab]-[a-z0-9-]{8,}|"
    r"ya29\.[a-z0-9_-]{4,}|eyj[a-z0-9_-]{16,}|akia[0-9A-Z]{16}|"
    r"glpat-[a-z0-9_-]{16,}|bearer\s+[a-z0-9._-]{8,})"
)


def safe_error_for_user(message: str | None) -> str:
    return _SECRET_PATTERN.sub("***", message) if message else ""


def safe_dict(details: dict[str, Any] | None) -> dict[str, Any]:
    return {
        k: safe_error_for_user(v) if isinstance(v, str) else v for k, v in (details or {}).items()
    }
