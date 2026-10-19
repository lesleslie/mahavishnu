"""Subprocess env stripping contract for the Pi pool (D1, BLOCKER #3).

REQ-BIFROST-014: the runtime denylist at
``mahavishnu.pools.pi_pool._FORBIDDEN_ENV_PREFIXES`` is the actual
security boundary for the PiPool subprocess env forwarding. The
positive ``env_allowlist`` in :class:`PiPool` is the second line of
defense; this test pins the denylist directly.

Req: REQ-PI-003
"""  # req: REQ-PI-003

from __future__ import annotations

import os

import pytest

from mahavishnu.pools.pi_pool import (
    _FORBIDDEN_ENV_PREFIXES,
    _build_subprocess_env,
)


@pytest.fixture
def seed_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-populate the parent env with the secrets we expect to be stripped."""
    monkeypatch.setenv("MAHAVISHNU_AUTH_SECRET", "super-secret-mahavishnu-token-value")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax-abcdef1234567890XYZ")
    monkeypatch.setenv("ZAI_API_KEY", "sk-zai-abcdef1234567890XYZ")
    monkeypatch.setenv("DHARA_API_TOKEN", "mcp-secret-token-value")
    monkeypatch.setenv("AKOSHA_AUTH_SECRET", "akosha-secret-token-value")
    monkeypatch.setenv("SESSION_BUDDY_API_KEY", "session-buddy-secret-value")
    monkeypatch.setenv("BIFROST_API_KEY", "bifrost-secret-token-value")
    monkeypatch.setenv("ONEIRIC_BIFROST_AUTH_TOKEN", "oneiric-secret-token-value")
    # Plus a benign value that MUST survive.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")


def test_build_subprocess_env_strips_minimax_and_mahavishnu_secrets(
    seed_secrets: None,
) -> None:
    """``_build_subprocess_env`` must NEVER copy secret-shaped env keys."""
    env = _build_subprocess_env(env_allowlist=("PATH",))
    forbidden = {
        "MAHAVISHNU_AUTH_SECRET",
        "MINIMAX_API_KEY",
        "ZAI_API_KEY",
        "DHARA_API_TOKEN",
        "AKOSHA_AUTH_SECRET",
        "SESSION_BUDDY_API_KEY",
        "BIFROST_API_KEY",
        "ONEIRIC_BIFROST_AUTH_TOKEN",
    }
    for key in forbidden:
        assert key not in env, f"{key} leaked to subprocess env: {env.get(key)!r}"
    # Benign keys MUST survive.
    assert "PATH" in env
    assert env["PATH"] == "/usr/bin:/bin"


def test_build_subprocess_env_forwards_allowlist_keys() -> None:
    """Keys in the env_allowlist that aren't on the denylist are forwarded."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENAI_API_KEY", "sk-openai-test-abcdef")
        mp.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8471/v1")
        mp.setenv("ANTHROPIC_API_KEY", "sk-anthropic-test-xyz")
        env = _build_subprocess_env(
            env_allowlist=("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY")
        )
    assert env["OPENAI_API_KEY"] == "sk-openai-test-abcdef"
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:8471/v1"
    assert env["ANTHROPIC_API_KEY"] == "sk-anthropic-test-xyz"


def test_build_subprocess_env_drops_allowlist_keys_matching_denylist() -> None:
    """Allowlist entries that match a denylist prefix are dropped at runtime.

    If a caller (or hostile config) puts a sensitive key in
    ``env_allowlist``, the subprocess env MUST NOT receive it. The
    model-level ``PiPoolSettings._npx_command_allowlist`` validator is
    the first line of defense (it rejects the config outright); this
    runtime denylist is the second.
    """
    sensitive_keys = {
        "MAHAVISHNU_AUTH_SECRET": "supersecret-1234567890",
        "MINIMAX_API_KEY": "minimax-key-abcdef",
        "ZAI_API_KEY": "zai-key-xyz",
        "DHARA_TOKEN": "mcp-tok-1",
        "AKOSHA_TOKEN": "akosha-tok-1",
        "SESSION_BUDDY_TOKEN": "sb-tok-1",
        "BIFROST_API_KEY": "bifrost-tok-1",
        "ONEIRIC_BIFROST_AUTH_TOKEN": "oneiric-tok-1",
    }
    with pytest.MonkeyPatch.context() as mp:
        for k, v in sensitive_keys.items():
            mp.setenv(k, v)
        # Caller passes ALL sensitive keys via env_allowlist (hostile config).
        env = _build_subprocess_env(env_allowlist=tuple(sensitive_keys.keys()))
    for k in sensitive_keys:
        assert k not in env, (
            f"runtime denylist leaked {k!r} to subprocess env; "
            f"got env keys: {sorted(env)}"
        )


def test_forbidden_env_prefixes_denylist_is_tuple() -> None:
    """The denylist must be a tuple (immutable) — accidental runtime
    mutation of a mutable denylist would be a security regression.
    ``tuple[str, ...]`` is the contract.
    """
    import typing

    assert isinstance(_FORBIDDEN_ENV_PREFIXES, tuple)
    hints = typing.get_type_hints(
        __import__("mahavishnu.pools.pi_pool", fromlist=["_FORBIDDEN_ENV_PREFIXES"])
    )
    assert hints.get("_FORBIDDEN_ENV_PREFIXES") == tuple[str, ...]


def test_forbidden_env_prefixes_includes_mahavishnu_and_bifrost() -> None:
    """REQ-BIFROST-014: ``MAHAVISHNU_`` covers the mahavishnu operator's
    own config; ``BIFROST_`` covers the bifrost gateway config (any env
    var controlling the oneiric router or the legacy local bifrost).
    These must not leak into a PiPool subprocess.
    """
    assert "MAHAVISHNU_" in _FORBIDDEN_ENV_PREFIXES
    assert "BIFROST_" in _FORBIDDEN_ENV_PREFIXES
    assert "ONEIRIC_" in _FORBIDDEN_ENV_PREFIXES


def test_usr_bin_env_npx_is_accepted() -> None:
    """`/usr/bin/env npx ...` is the canonical path-agnostic form and is allowed."""
    from mahavishnu.core.config import PiPoolSettings

    ps = PiPoolSettings(
        npx_command=("/usr/bin/env", "npx", "@earendil-works/pi-coding-agent"),
    )  # type: ignore[arg-type]
    assert ps.npx_command[0] == "/usr/bin/env"
    assert ps.npx_command[1] == "npx"


def test_usr_bin_env_requires_npx_as_second_arg() -> None:
    """`/usr/bin/env <other>` is rejected (would spawn <other> directly)."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    # /usr/bin/env sh -c 'evil' @pkg — would spawn `sh` and bypass allowlist.
    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(
            npx_command=("/usr/bin/env", "sh", "-c", "evil", "@earendil-works/pi-coding-agent"),
        )  # type: ignore[arg-type]
    assert "must be 'npx'" in str(excinfo.value)


def test_shell_binary_in_argv_is_rejected() -> None:
    """Shell binaries (sh/bash/zsh) anywhere in argv are rejected."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(
            npx_command=("npx", "sh", "-c", "evil", "@earendil-works/pi-coding-agent"),
        )  # type: ignore[arg-type]
    assert "shell-binary" in str(excinfo.value)


def test_shell_flag_dash_c_is_rejected() -> None:
    """``-c`` flag anywhere in argv is rejected (would shell-interpret)."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(
            npx_command=("npx", "-y", "-c", "evil", "@earendil-works/pi-coding-agent"),
        )  # type: ignore[arg-type]
    assert "shell-flag" in str(excinfo.value)
