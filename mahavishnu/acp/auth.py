"""Bearer authentication for the ACP server.

Per plan §Phase 2 Decision 5 (Threat model) and the bearer-gate contract
in §Phase 2 Task 1:

- The bearer is loaded from ``MAHAVISHNU_ACP_BEARER_TOKEN`` (env var) OR
  ``MAHAVISHNU_ACP_BEARER_TOKEN_FILE`` (file path with mode 0600). The two
  modes are **mutually exclusive**.
- ``serve()`` refuses to start if neither is set (fail-closed; the only
  fail-open behavior in this module is when an explicit token is passed
  for testing).
- The bearer is **popped from ``os.environ`` immediately after the read**
  so child processes (pool workers, OTel exporter, git subprocesses)
  do not inherit it.
- Comparison uses ``secrets.compare_digest`` (timing-safe). Plain ``==``
  or ``!=`` on the token is forbidden — the dispatcher tests assert
  ``compare_digest`` is called.
- A ``BearerRedactionFilter`` for ``logging.Filter`` replaces any
  occurrence of the bearer value with ``<redacted-bearer>`` on every
  record before it reaches the handler. The Phase 4 e2e test asserts
  no log line contains the original bearer.

The ``get_bearer_token`` function is the single entry point and uses a
module-level cached sentinel so it's safe to call multiple times during
startup without re-reading the env. The ``acquire_bearer`` function does
the read + env-pop and is called once at server startup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import secrets
from typing import Final

from mahavishnu.acp.errors import AUTH_INVALID, ACPError

# Sentinel for the lazy singleton. ``None`` means "not yet read".
_UNSET: Final = object()

_cached_token: object = _UNSET

# Env var names (public so the dispatcher / CLI can also reference them).
ENV_BEARER_TOKEN: Final = "MAHAVISHNU_ACP_BEARER_TOKEN"
ENV_BEARER_TOKEN_FILE: Final = "MAHAVISHNU_ACP_BEARER_TOKEN_FILE"

# Required minimum length for the bearer (sanity guard; 32+ bytes recommended
# in the operator doc). Tokens shorter than this are rejected at startup.
_MIN_BEARER_LENGTH: Final = 16

# Redaction marker used by ``BearerRedactionFilter``.
REDACTED_BEARER: Final = "<redacted-bearer>"


def _read_token_from_env() -> str | None:
    """Read the bearer token from the env var (or env-var-file).

    Returns ``None`` if neither is set. Raises ``ACPError`` for malformed
    configurations (both env and file set, file mode wrong, file unreadable).
    """
    env_token = os.environ.get(ENV_BEARER_TOKEN)
    env_file = os.environ.get(ENV_BEARER_TOKEN_FILE)
    if env_token is not None and env_file is not None:
        raise ACPError(
            AUTH_INVALID,
            f"{ENV_BEARER_TOKEN} and {ENV_BEARER_TOKEN_FILE} are mutually exclusive",
        )
    if env_token is not None:
        return env_token
    if env_file is not None:
        path = Path(env_file)
        # Mode check: refuse if file is group- or world-readable.
        try:
            mode = path.stat().st_mode & 0o777
        except OSError as exc:
            raise ACPError(
                AUTH_INVALID,
                f"bearer token file {env_file} is unreadable: {exc}",
            ) from exc
        if mode & 0o077:
            raise ACPError(
                AUTH_INVALID,
                f"bearer token file {env_file} has permissive mode {oct(mode)}; expected mode 0600",
            )
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ACPError(
                AUTH_INVALID,
                f"bearer token file {env_file} could not be read: {exc}",
            ) from exc
    return None


def acquire_bearer() -> str | None:
    """Read the bearer from the environment, then ``os.environ.pop`` it.

    The bearer is loaded exactly once per process. The ``MAHAVISHNU_ACP_BEARER_TOKEN``
    env var is removed from ``os.environ`` immediately after read so
    child processes do not inherit it. Returns ``None`` if neither the
    env var nor the file is set (the dispatcher fails closed in that case).

    Caches the result in ``_cached_token`` so subsequent calls return the
    same value without re-reading. The cache is module-level state — fine
    for a single-process server, not safe across forks (the dispatcher is
    a single process by design per plan Decision 5).
    """
    global _cached_token
    if _cached_token is not _UNSET:
        if isinstance(_cached_token, str):
            return _cached_token
        return None
    token = _read_token_from_env()
    # Pop the env vars so child processes don't inherit them.
    os.environ.pop(ENV_BEARER_TOKEN, None)
    os.environ.pop(ENV_BEARER_TOKEN_FILE, None)
    _cached_token = token
    return token


def reset_cached_bearer_for_tests() -> None:
    """Clear the cached bearer so tests can re-acquire with a different env."""
    global _cached_token
    _cached_token = _UNSET


def verify_token(provided: str, expected: str) -> bool:
    """Constant-time comparison of two bearer tokens.

    Uses ``secrets.compare_digest``; plain ``==``/``!=`` on tokens is
    timing-attack-vulnerable and forbidden. Fail-closed: empty or
    non-string inputs return ``False`` (no token provided means no
    authentication granted).
    """
    if not isinstance(provided, str) or not isinstance(expected, str):
        return False
    # Fail-closed: empty token does not authenticate, even if both sides
    # are empty (``compare_digest`` on two empty byte strings would
    # otherwise return ``True``).
    if not provided or not expected:
        return False
    # ``compare_digest`` requires equal-length byte strings for the
    # constant-time guarantee. Pad to the longer length with NULs so
    # unequal-length inputs don't short-circuit.
    a = provided.encode("utf-8")
    b = expected.encode("utf-8")
    n = max(len(a), len(b))
    a = a + b"\x00" * (n - len(a))
    b = b + b"\x00" * (n - len(b))
    return secrets.compare_digest(a, b)


def validate_token_strength(token: str) -> None:
    """Raise ``ACPError`` if *token* doesn't meet the minimum length bar.

    The 16-byte minimum is a sanity guard, not a security boundary; the
    operator doc recommends 32+ bytes. Tokens shorter than this are
    rejected at server startup.
    """
    if len(token) < _MIN_BEARER_LENGTH:
        raise ACPError(
            AUTH_INVALID,
            f"bearer token too short ({len(token)} bytes); minimum is {_MIN_BEARER_LENGTH}",
        )


class BearerRedactionFilter(logging.Filter):
    """Logging filter that replaces the bearer value with ``REDACTED_BEARER``.

    Attach to every handler on the ``mahavishnu.acp`` logger so bearer
    tokens never appear in log output. The Phase 4 e2e test asserts no
    log line contains the original bearer value.
    """

    def __init__(self, bearer: str) -> None:
        super().__init__()
        self._bearer = bearer

    def filter(self, record: logging.LogRecord) -> bool:
        # ``getMessage`` is the post-format string. Mutating the message
        # avoids changing the original ``record.args`` (so log formatters
        # still work on structured args).
        if self._bearer and self._bearer in record.getMessage():
            record.msg = record.getMessage().replace(self._bearer, REDACTED_BEARER)
            record.args = ()
        return True


__all__ = [
    "ENV_BEARER_TOKEN",
    "ENV_BEARER_TOKEN_FILE",
    "REDACTED_BEARER",
    "BearerRedactionFilter",
    "acquire_bearer",
    "reset_cached_bearer_for_tests",
    "validate_token_strength",
    "verify_token",
]
