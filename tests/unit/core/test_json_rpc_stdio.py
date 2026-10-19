"""Tests for the JSON-RPC stdio transport and its env-var security boundary.

The PiPool subprocess inherits env vars via ``env_allowlist`` (a
positive list of allowed prefixes). The
``_FORBIDDEN_ENV_PREFIXES`` denylist at
``mahavishnu/core/json_rpc_stdio.py:76`` is the second line of
defense — it strips any prefixed env var even if the
``env_allowlist`` accidentally or maliciously includes it.

REQ-BIFROST-014 (bifrost plan §5 Phase 3): the denylist must
include ``MAHAVISHNU_`` and ``BIFROST_`` (the latter covers the
legacy ``MAHAVISHNU_BIFROST__*`` prefix and the new
``ONEIRIC_BIFROST_*`` prefix; the bare ``BIFROST_`` prefix also
catches ``BIFROST_ALLOW_REMOTE`` and ``BIFROST_LOG_OPERATOR_IDENTITY``).
"""

from __future__ import annotations

from mahavishnu.core.json_rpc_stdio import _FORBIDDEN_ENV_PREFIXES


def test_forbidden_env_prefixes_includes_mahavishnu_and_bifrost() -> None:
    """REQ-BIFROST-014: the denylist is the actual security boundary
    for the PiPool subprocess env forwarding. ``MAHAVISHNU_`` is the
    mahavishnu operator's own config; ``BIFROST_`` covers the
    bifrost gateway config (any env var controlling the oneiric
    router or the legacy local bifrost) — these must not leak
    into a PiPool subprocess.
    """
    assert "MAHAVISHNU_" in _FORBIDDEN_ENV_PREFIXES
    assert "BIFROST_" in _FORBIDDEN_ENV_PREFIXES


def test_forbidden_env_prefixes_denylist_is_tuple() -> None:
    """The denylist must be a tuple (immutable) — accidental
    runtime mutation of a mutable denylist would be a security
    regression. ``tuple[str, ...]`` is the contract.
    """
    import typing

    assert isinstance(_FORBIDDEN_ENV_PREFIXES, tuple)
    # The runtime annotation at json_rpc_stdio.py:76 is
    # ``tuple[str, ...]``; the type system enforces this at
    # definition time.
    hints = typing.get_type_hints(
        __import__("mahavishnu.core.json_rpc_stdio", fromlist=["_FORBIDDEN_ENV_PREFIXES"])
    )
    assert hints.get("_FORBIDDEN_ENV_PREFIXES") == tuple[str, ...]
