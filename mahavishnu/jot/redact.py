"""Capture-time redaction: ~17 regex patterns across 3 tiers.

See spec §"Redaction" and D2 (moderate scope).

H4 fix: each pattern is compiled defensively (try/except). Patterns that fail
to compile are skipped (logged via the standard Python warnings module at
module load). A bad pattern must never crash the hook before logging is reachable.
"""
from __future__ import annotations

import hashlib
import re
from re import Pattern
import sys

# Pattern format: (raw_regex_string, tier_label)
# Tier labels: "secret", "credential", "url", "env"
_PATTERNS_RAW: list[tuple[str, str]] = [
    # Tier 1: Secrets
    (r"AKIA[0-9A-Z]{16}", "secret"),  # AWS access key
    (r"ghp_[a-zA-Z0-9]{36}", "secret"),  # GitHub PAT (classic)
    (r"gho_[a-zA-Z0-9]{36}", "secret"),  # GitHub OAuth
    (r"ghu_[a-zA-Z0-9]{36}", "secret"),  # GitHub user-to-server
    (r"ghs_[a-zA-Z0-9]{36}", "secret"),  # GitHub server-to-server
    (r"ghr_[a-zA-Z0-9]{36}", "secret"),  # GitHub refresh
    (r"sk-ant-[a-zA-Z0-9-]{20,}", "secret"),  # Anthropic key (must come before generic sk-)
    (r"sk-[a-zA-Z0-9]{20,}", "secret"),  # OpenAI key
    (r"xox[baprs]-[a-zA-Z0-9-]{10,}", "secret"),  # Slack tokens
    (r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "secret"),  # JWT
    (r"Bearer\s+[a-zA-Z0-9_.-]+", "secret"),  # Bearer token
    # Tier 2: Credentials
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "credential"),  # Email
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "credential"),  # US phone
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "credential"),  # IPv4
    # Tier 3: URLs + env-style
    (r"https?://[^\s]+", "url"),  # HTTP(S) URLs
    (r"\.env(\.\w+)?", "env"),  # .env-style references
    (r"-----BEGIN [A-Z ]+PRIVATE KEY-----", "env"),  # SSH private key headers
]


def _compile_patterns() -> list[tuple[Pattern[str], str]]:
    """H4 fix: defensively compile each pattern; skip (log) any that fail.

    Returns a list of (compiled_pattern, tier) tuples. Patterns that fail to
    compile are logged via print() to stderr (avoiding circular dependency on
    _log_error which lives in jot_capture.py).
    """
    compiled: list[tuple[Pattern[str], str]] = []
    for raw, tier in _PATTERNS_RAW:
        try:
            compiled.append((re.compile(raw), tier))
        except re.error as exc:
            # Log to stderr — don't crash module load. Spec §"Stdlib Hygiene"
            # says no `logging`, but print to stderr is acceptable for this
            # one-shot module-load diagnostic.
            print(
                f"[jot.redact] skipping pattern {raw!r}: {exc}",
                file=sys.stderr,
            )
    return compiled


_PATTERNS: list[tuple[Pattern[str], str]] = _compile_patterns()

# Exported regex for sub-plan 2's read surface to identify redacted regions
REDACTED_PATTERN = r"\[REDACTED:(?:secret|credential|url|env):[0-9a-f]{8}\]"


def _make_replacement(match: re.Match[str], tier: str) -> str:
    """Build the replacement string for a redaction match."""
    secret = match.group(0)
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
    return f"[REDACTED:{tier}:{digest}]"


def redact_text(text: str) -> str:
    """Apply all redaction patterns to text. Returns redacted text.

    Patterns are applied in tier order: secrets first (most specific), then
    credentials, then URLs + env-style. First match wins per pattern; overlap
    between patterns is acceptable (e.g., a URL in a JWT is redacted twice).

    The replacement format `[REDACTED:<tier>:<hash>]` allows sub-plan 2's
    read surface to detect and display redacted regions. The hash is a
    one-way sha256 prefix that enables correlation ("same secret?") without
    reversing the redaction.
    """
    out = text
    for pattern, tier in _PATTERNS:
        # Capture tier via default argument to avoid B023 (late binding closure)
        replacement = (lambda t: (lambda m: _make_replacement(m, t)))(tier)
        out = pattern.sub(replacement, out)
    return out
