"""npx_command allowlist validation contract for the Pi pool (D1, BLOCKER #2).

The v1.x pi-coding-agent is a one-shot CLI — there is no ``--rpc`` flag.
This file pins the post-rewrite validator: ``npx`` (or
``/usr/bin/env`` wrapping ``npx``, or ``/usr/local/bin/npx``) at cmd[0],
no shell-bypass argv, and the agent package name is present.

Req: REQ-PI-001
"""  # req: REQ-PI-001

from __future__ import annotations

import pytest

from mahavishnu.core.config import PiPoolSettings
from mahavishnu.core.errors import ConfigurationError


def test_default_npx_command_is_accepted() -> None:
    """The shipped default must satisfy the validator (regression guard)."""
    ps = PiPoolSettings()
    assert ps.npx_command[0] in {"npx", "/usr/bin/env", "/usr/local/bin/npx"}
    assert "@earendil-works/pi-coding-agent" in " ".join(ps.npx_command)
    # v1.x has no ``--rpc``; ensure we did not regress to the old surface.
    assert "--rpc" not in ps.npx_command


@pytest.mark.parametrize(
    "bad_command",
    [
        ("/bin/sh", "-c", "evil"),
        ("/usr/bin/curl", "evil.com"),
        ("python", "evil.py"),
        ("bash", "-i"),
        ("", "npx"),  # empty first element
    ],
)
def test_npx_command_rejects_non_npx_binary(bad_command: tuple[str, ...]) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(npx_command=bad_command)  # type: ignore[arg-type]
    # The error must NEVER be silent (i.e. must raise).
    assert "npx" in str(excinfo.value).lower()


def test_npx_command_rejects_wrong_package() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(
            npx_command=("npx", "-y", "evil-package"),  # type: ignore[arg-type]
        )
    assert "@earendil-works/pi-coding-agent" in str(excinfo.value)


@pytest.mark.parametrize(
    "ok_command",
    [
        ("npx", "-y", "@earendil-works/pi-coding-agent"),
        ("/usr/bin/env", "npx", "@earendil-works/pi-coding-agent"),
        ("/usr/local/bin/npx", "@earendil-works/pi-coding-agent"),
        # Version pin via ``@`` syntax.
        ("npx", "-y", "@earendil-works/pi-coding-agent@1.3.0"),
    ],
)
def test_npx_command_accepts_canonical_paths(ok_command: tuple[str, ...]) -> None:
    """All three canonical binaries are accepted; version-pinned forms too."""
    ps = PiPoolSettings(npx_command=ok_command)  # type: ignore[arg-type]
    assert ps.npx_command == ok_command
