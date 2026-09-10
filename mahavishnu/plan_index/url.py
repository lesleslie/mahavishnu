"""Git remote URL normalization (security: REQ-PLAN-011).

normalize_repo_url runs BEFORE plan_id derivation (D4). The normalized
form is what gets persisted to Dhara AND fed into the SHA. Three URL
forms of the same repo produce the same normalized output:

    git@github.com:foo/bar.git
    https://github.com/foo/bar.git
    ssh://git@github.com/foo/bar.git

    →
    github.com/<hash_of_foo/bar>

The hash is sha256("/".join(path_segments)).hexdigest()[:12].

Security notes:
    * Userinfo (user:pass@ or user@) is stripped so credentials never
      land in Dhara's log or the SHA.
    * Path segments are hashed so the repo structure (e.g. internal
      org/repo names) is not exposed in persisted records.
    * Control characters (NUL, CR, LF, DEL, etc.) are rejected so the
      input cannot smuggle log-injection or parser-confusion payloads.
    * Only the three canonical git remote URL forms are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata
from urllib.parse import urlparse

__all__ = ["RepoUrlRejectedError", "normalize_repo_url"]

# URL pattern: scheme + host + path. Reject anything else.
_ALLOWED_PATTERN = re.compile(r"^(git@|https?://|ssh://)[A-Za-z0-9._-]+(/|:).+$")
_PATH_SEGMENT_DELIM = "/"
_HASH_PREFIX_LEN = 12


@dataclass(frozen=True, slots=True)
class RepoUrlRejectedError(ValueError):
    """Raised by normalize_repo_url when the input cannot be normalized."""

    raw: str
    reason: str

    def __str__(self) -> str:
        return f"RepoUrlRejectedError({self.reason!r}, raw={self.raw!r})"


def _strip_userinfo(url: str) -> str:
    """Strip userinfo (user:pass@ or user@) from a URL.

    Handles three forms:
    - git@host:path (shorthand) -> ssh://host/path
    - ssh://user@host/path -> ssh://host/path
    - https://user:pass@host/path -> https://host/path
    """
    if url.startswith("git@"):
        host_part, _, path_part = url.partition(":")
        host = host_part.removeprefix("git@")
        return f"ssh://{host}/{path_part}"

    parsed = urlparse(url)
    if parsed.username:
        netloc = parsed.hostname or ""
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return url


def _hash_path_segments(path: str) -> str:
    """Hash path segments so repo structure is not exposed in Dhara."""
    cleaned = path.strip("/").removesuffix(".git")
    segments = cleaned.split(_PATH_SEGMENT_DELIM)
    joined = _PATH_SEGMENT_DELIM.join(segments)
    return hashlib.sha256(joined.encode()).hexdigest()[:_HASH_PREFIX_LEN]


def normalize_repo_url(raw: str, *, raise_on_reject: bool = False) -> str | None:
    """Normalize a git remote URL.

    Returns:
        The normalized form "host/<path_hash>" if the URL is well-formed.
        None if rejected (default behavior).

    Raises:
        RepoUrlRejectedError if raise_on_reject=True and the URL is rejected.

    The normalized form is stable across the three canonical URL formats
    (git@, https://, ssh://), lowercase, and has its path hashed.
    """
    if not isinstance(raw, str):
        if raise_on_reject:
            raise RepoUrlRejectedError(str(raw), "not a string")
        return None

    # Control character check (NUL, CR, LF, DEL, etc.) — always raises.
    # These are nearly always an attack vector (log injection, parser
    # confusion) so we never silently accept them. Also catches Unicode
    # line separator (U+2028, category Zl) and paragraph separator
    # (U+2029, category Zp), which are valid log-injection vectors
    # that bypass an ASCII-only check.
    if any(ord(c) < 0x20 or ord(c) == 0x7F or unicodedata.category(c) in ("Zl", "Zp") for c in raw):
        raise RepoUrlRejectedError(raw, "control characters")

    # Strip userinfo first so the pattern check sees host-only URLs.
    stripped = _strip_userinfo(raw)

    if not _ALLOWED_PATTERN.match(stripped):
        if raise_on_reject:
            raise RepoUrlRejectedError(raw, "does not match allowed pattern")
        return None

    try:
        parsed = urlparse(stripped)
    except ValueError as exc:
        if raise_on_reject:
            raise RepoUrlRejectedError(raw, "urlparse failure") from exc
        return None

    host = (parsed.hostname or "").lower()
    if not host:
        if raise_on_reject:
            raise RepoUrlRejectedError(raw, "no host")
        return None

    path_hash = _hash_path_segments(parsed.path or "")
    return f"{host}/{path_hash}"
