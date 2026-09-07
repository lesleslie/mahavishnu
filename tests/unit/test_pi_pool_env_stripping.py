"""Subprocess env stripping contract for the Pi pool (D1, BLOCKER #3).

Req: REQ-PI-003
"""  # req: REQ-PI-003

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.json_rpc_stdio import JSONRPCStdioClient
from mahavishnu.core.errors import PiProtocolError


class _FakeProcess:
    """Bare-minimum stand-in for an asyncio.subprocess.Process."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin = None
        self.stdout = None

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


class _CaptureWriter:
    """Captures all writes for inspection by tests."""

    def __init__(self) -> None:
        self.buffer: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.buffer.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    def is_closing(self) -> bool:
        return False


class _CaptureReader:
    async def readline(self) -> bytes:
        return b""


@pytest.fixture
def seed_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-populate the parent env with the secrets we expect to be stripped."""
    monkeypatch.setenv("MAHAVISHNU_AUTH_SECRET", "super-secret-mahavishnu-token-value")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax-abcdef1234567890XYZ")
    monkeypatch.setenv("ZAI_API_KEY", "sk-zai-abcdef1234567890XYZ")
    monkeypatch.setenv("DHARA_API_TOKEN", "dhara-secret-token-value")
    monkeypatch.setenv("AKOSHA_AUTH_SECRET", "akosha-secret-token-value")
    monkeypatch.setenv("SESSION_BUDDY_API_KEY", "session-buddy-secret-value")
    # Plus a benign value that MUST survive.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")


@pytest.mark.asyncio
async def test_subprocess_env_strips_minimax_and_mahavishnu_secrets(
    seed_secrets: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the JSON-RPC client never copies secret-shaped env keys.

    We exercise ``_build_subprocess_env`` via the stream_factory seam so no
    real subprocess is spawned. The ``--version`` startup probe also uses
    ``create_subprocess_exec`` — we patch that too.
    """
    captured_env: dict[str, str] = {}

    def stream_factory(*, env):  # type: ignore[no-untyped-def]
        captured_env.update(env)
        return _CaptureReader(), _CaptureWriter()

    # Force-start a client without spawning a real subprocess.
    client = JSONRPCStdioClient(
        command=("npx", "@earendil-works/pi-coding-agent", "--rpc"),
        env=("PATH", "HOME"),
        stream_factory=stream_factory,
    )
    # Patch BOTH subprocess paths: the main RPC spawn AND the --version probe.
    fake_proc = AsyncMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    fake_proc.wait = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=fake_proc),
    )
    try:
        await client.start()
    except PiProtocolError:
        pass  # reader loop fails fast; we don't care — env is captured at start().

    # Sensitive keys must NEVER be in the subprocess env.
    forbidden = {
        "MAHAVISHNU_AUTH_SECRET",
        "MINIMAX_API_KEY",
        "ZAI_API_KEY",
        "DHARA_API_TOKEN",
        "AKOSHA_AUTH_SECRET",
        "SESSION_BUDDY_API_KEY",
    }
    for key in forbidden:
        assert key not in captured_env, f"{key} leaked to subprocess env: {captured_env[key]!r}"
    # Benign keys MUST survive.
    assert "PATH" in captured_env
    assert captured_env["PATH"] == "/usr/bin:/bin"


def test_build_subprocess_env_does_not_carry_secrets() -> None:
    """Direct unit test of ``_build_subprocess_env`` without asyncio."""
    os.environ["MAHAVISHNU_AUTH_SECRET"] = "leaked-mahavishnu-token"
    os.environ["MINIMAX_API_KEY"] = "leaked-minimax-token"
    try:
        client = JSONRPCStdioClient(
            command=("npx", "@earendil-works/pi-coding-agent", "--rpc"),
            env=("PATH",),
        )
        env = client._build_subprocess_env()
        assert "MAHAVISHNU_AUTH_SECRET" not in env
        assert "MINIMAX_API_KEY" not in env
        # PATH survives.
        assert "PATH" in env
    finally:
        os.environ.pop("MAHAVISHNU_AUTH_SECRET", None)
        os.environ.pop("MINIMAX_API_KEY", None)


def test_env_allowlist_does_not_include_sensitive_prefixes() -> None:
    """The default env_allowlist MUST NOT contain sensitive env keys."""
    client = JSONRPCStdioClient(
        command=("npx", "@earendil-works/pi-coding-agent", "--rpc"),
        env=("PATH",),
    )
    allowlist = client._explicit_env
    sensitive_prefixes = (
        "MAHAVISHNU_",
        "MINIMAX_",
        "ZAI_",
        "DHARA_",
        "AKOSHA_",
        "SESSION_BUDDY_",
    )
    for key in allowlist:
        for prefix in sensitive_prefixes:
            assert not key.startswith(prefix), (
                f"env_allowlist contains sensitive prefix {prefix}: {key}"
            )


def test_runtime_denylist_strips_sensitive_keys_from_env() -> None:
    """Runtime denylist in _build_subprocess_env strips sensitive keys.

    If a caller (or hostile config) puts a sensitive key in ``env``,
    the subprocess env MUST NOT receive it. This is the second line of
    defense after the model-level ``_env_allowlist_denylist`` validator.

    Req: REQ-PI-003
    """  # req: REQ-PI-003
    sensitive_keys = {
        "MAHAVISHNU_AUTH_SECRET": "supersecret-1234567890",
        "MINIMAX_API_KEY": "minimax-key-abcdef",
        "ZAI_API_KEY": "zai-key-xyz",
        "DHARA_TOKEN": "dhara-tok-1",
        "AKOSHA_TOKEN": "akosha-tok-1",
        "SESSION_BUDDY_TOKEN": "sb-tok-1",
    }
    with pytest.MonkeyPatch.context() as mp:
        for k, v in sensitive_keys.items():
            mp.setenv(k, v)
        # Caller passes ALL sensitive keys via env (simulating a hostile config).
        client = JSONRPCStdioClient(
            command=("npx", "@earendil-works/pi-coding-agent", "--rpc"),
            env=tuple(sensitive_keys.keys()),
        )
        subprocess_env = client._build_subprocess_env()
        for k in sensitive_keys:
            assert k not in subprocess_env, (
                f"runtime denylist leaked {k!r} to subprocess env; "
                f"got subprocess_env keys: {sorted(subprocess_env)}"
            )


def test_env_allowlist_validator_rejects_sensitive_keys() -> None:
    """PiPoolSettings(env_allowlist=...) rejects sensitive-prefix keys at validation."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(env_allowlist=("PATH", "MAHAVISHNU_AUTH_SECRET"))
    assert "MAHAVISHNU_AUTH_SECRET" in str(excinfo.value)
    assert "sensitive" in str(excinfo.value).lower()


def test_usr_bin_env_requires_npx_as_second_arg() -> None:
    """`/usr/bin/env <other>` is rejected (would spawn <other> directly)."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    # /usr/bin/env sh -c 'evil' --rpc @pkg — would spawn `sh` and bypass allowlist.
    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(
            npx_command=("/usr/bin/env", "sh", "-c", "evil", "--rpc", "@earendil-works/pi-coding-agent"),
        )  # type: ignore[arg-type]
    assert "must be 'npx'" in str(excinfo.value)


def test_usr_bin_env_npx_is_accepted() -> None:
    """`/usr/bin/env npx ...` is the canonical path-agnostic form and is allowed."""
    from mahavishnu.core.config import PiPoolSettings

    ps = PiPoolSettings(
        npx_command=("/usr/bin/env", "npx", "@earendil-works/pi-coding-agent", "--rpc"),
    )  # type: ignore[arg-type]
    assert ps.npx_command[0] == "/usr/bin/env"
    assert ps.npx_command[1] == "npx"


def test_shell_binary_in_argv_is_rejected() -> None:
    """Shell binaries (sh/bash/zsh) anywhere in argv are rejected."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(
            npx_command=("npx", "sh", "-c", "evil", "--rpc", "@earendil-works/pi-coding-agent"),
        )  # type: ignore[arg-type]
    assert "shell-binary" in str(excinfo.value)


def test_shell_flag_dash_c_is_rejected() -> None:
    """``-c`` flag anywhere in argv is rejected (would shell-interpret)."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(
            npx_command=("npx", "-y", "-c", "evil", "--rpc", "@earendil-works/pi-coding-agent"),
        )  # type: ignore[arg-type]
    assert "shell-flag" in str(excinfo.value)