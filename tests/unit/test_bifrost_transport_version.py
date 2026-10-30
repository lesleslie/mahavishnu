"""Tests for the pinned Bifrost transport version.

The npm package ``@maximhq/bifrost`` is only a launcher: it downloads the
native ``bifrost-http`` binary from ``downloads.getmaxim.ai`` and resolves
``latest`` on every boot. Unpinned, an upstream release silently replaces
the binary on the next restart -- which is how the EBADARCH failure of
2026-10-29 (an arm64 build on an x86_64 host) reached a running deployment
and took Claude Code down with it.

These tests pin three things:

1. the version is pinned and in the format the launcher accepts,
2. the plist and the in-code constant agree, and
3. the launcher that receives the flag actually understands it.
"""

from __future__ import annotations

import importlib
import json
import plistlib
import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mahavishnu.bifrost import gateway
from mahavishnu.bifrost.paths import BIFROST_TRANSPORT_VERSION

if TYPE_CHECKING:
    from pathlib import Path

#: The launcher's own validator accepts ``vX.Y.Z`` or ``latest``.
_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


@pytest.fixture
def _scratch_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep ``launch_bifrost`` off the operator's real filesystem."""
    monkeypatch.setattr(gateway, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(gateway, "READY_FILE", tmp_path / "ready" / "bifrost.ready")
    monkeypatch.setattr(gateway, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(gateway, "LOG_OUT", tmp_path / "logs" / "bifrost.log")
    monkeypatch.setattr(gateway, "LOG_ERR", tmp_path / "logs" / "bifrost.err")
    monkeypatch.setattr(gateway, "TARGET_CONFIG", tmp_path / "app" / "config.json")


def _launcher(tmp_path: Path, *, supports_flag: bool) -> Path:
    """Write a stand-in launcher script.

    A launcher that supports the flag must both recognise it and remove it
    from argv before exec'ing the transport binary -- see
    ``gateway.launcher_supports_transport_version``.
    """
    path = tmp_path / "bin.js"
    if supports_flag:
        body = 'const v = "--transport-version";\nargs.splice(i, 1);'
    else:
        body = "const v = 0;"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# the pin itself
# ---------------------------------------------------------------------------


def test_transport_version_is_pinned_and_well_formed() -> None:
    """The pin is a concrete version, not ``latest``."""
    assert BIFROST_TRANSPORT_VERSION != "latest"
    assert _VERSION_RE.match(BIFROST_TRANSPORT_VERSION), (
        f"{BIFROST_TRANSPORT_VERSION!r} is not in the format the launcher accepts"
    )


def test_plist_agrees_with_the_pinned_constant() -> None:
    """The plist and the code must not drift apart.

    The plist is what launchd actually hands the process; the constant is the
    fallback for a foreground run. Two sources of truth need one guard.
    """
    plist_path = gateway.REPO_ROOT / "config" / "launchd" / "ai.bifrost.gateway.plist"
    with plist_path.open("rb") as fh:
        plist = plistlib.load(fh)

    env = plist.get("EnvironmentVariables", {})
    assert env.get("BIFROST_TRANSPORT_VERSION") == BIFROST_TRANSPORT_VERSION, (
        "config/launchd/ai.bifrost.gateway.plist and "
        "mahavishnu/bifrost/paths.py disagree on the transport version"
    )


# ---------------------------------------------------------------------------
# launcher capability
# ---------------------------------------------------------------------------


def test_launcher_capability_is_detected(tmp_path: Path) -> None:
    """A launcher that understands the flag is recognised."""
    assert gateway.launcher_supports_transport_version(_launcher(tmp_path, supports_flag=True))
    assert not gateway.launcher_supports_transport_version(_launcher(tmp_path, supports_flag=False))


def test_launcher_that_merely_mentions_the_flag_is_not_trusted(tmp_path: Path) -> None:
    """A launcher that names the flag without removing it is not trusted.

    Such a launcher forwards the flag to the transport binary, which rejects
    unknown flags and refuses to boot -- the exact failure the check exists
    to prevent.
    """
    path = tmp_path / "bin.js"
    path.write_text("// TODO: support --transport-version someday\n", encoding="utf-8")
    assert not gateway.launcher_supports_transport_version(path)


def test_missing_launcher_reports_no_support(tmp_path: Path) -> None:
    """An unreadable launcher is treated as unsupported, not assumed good."""
    assert not gateway.launcher_supports_transport_version(tmp_path / "absent.js")


# ---------------------------------------------------------------------------
# the command the launcher receives
# ---------------------------------------------------------------------------


def _captured_command(monkeypatch: pytest.MonkeyPatch, launcher: Path | None) -> list[str]:
    """Run ``launch_bifrost`` with ``Popen`` stubbed out and return the argv."""
    captured: list[str] = []

    class _FakePopen:
        def __init__(self, cmd: list[str], **_kwargs: object) -> None:
            captured.extend(cmd)

    monkeypatch.setattr(gateway.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(gateway, "find_cached_bifrost_bin", lambda: launcher)
    gateway.launch_bifrost()
    return captured


def _without_stdbuf(cmd: list[str]) -> list[str]:
    """Drop the ``stdbuf`` prefix so the launcher argv can be asserted on.

    ``wrap_with_line_buffering`` prepends it only when coreutils is on PATH,
    which is host-dependent -- the assertion must not be.
    """
    if cmd[:3] == ["stdbuf", "-oL", "-eL"]:
        return cmd[3:]
    return cmd


def test_launch_bifrost_passes_the_pinned_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _scratch_paths: None
) -> None:
    """The launcher is told which transport version to fetch."""
    launcher = _launcher(tmp_path, supports_flag=True)

    cmd = _captured_command(monkeypatch, launcher)

    assert f"--transport-version={BIFROST_TRANSPORT_VERSION}" in cmd


def test_launch_bifrost_falls_back_to_npx_for_an_old_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _scratch_paths: None
) -> None:
    """A launcher too old to parse the flag is not used.

    The flag would be forwarded to the transport binary, which rejects
    unknown flags and refuses to boot. ``npx`` resolves a current launcher
    instead.
    """
    launcher = _launcher(tmp_path, supports_flag=False)

    cmd = _without_stdbuf(_captured_command(monkeypatch, launcher))

    assert cmd[:3] == ["npx", "-y", "@maximhq/bifrost"]
    assert f"--transport-version={BIFROST_TRANSPORT_VERSION}" in cmd


def test_launch_bifrost_uses_a_capable_cached_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _scratch_paths: None
) -> None:
    """A capable cached launcher is preferred over the npx round-trip."""
    launcher = _launcher(tmp_path, supports_flag=True)

    cmd = _without_stdbuf(_captured_command(monkeypatch, launcher))

    assert cmd[:2] == ["node", str(launcher)]


def test_transport_version_env_override() -> None:
    """The operator can roll back to a known-good build without a code edit.

    The version is read at import time, so the module is reloaded to observe
    the change -- and reloaded again afterwards so the override does not
    leak into other tests.
    """
    try:
        with patch.dict(gateway.os.environ, {"BIFROST_TRANSPORT_VERSION": "v2.3.2"}):
            reloaded = importlib.reload(gateway)
            assert reloaded.TRANSPORT_VERSION == "v2.3.2"
    finally:
        importlib.reload(gateway)


# ---------------------------------------------------------------------------
# which cached launcher gets used
# ---------------------------------------------------------------------------


def _cached_launcher(root: Path, directory: str, version: str) -> Path:
    """Lay out one npm ``_npx`` cache entry and return its launcher path."""
    launcher = root / directory / "node_modules" / "@maximhq" / "bifrost" / "bin.js"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("// launcher", encoding="utf-8")
    (launcher.parent / "package.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )
    return launcher


def test_cached_launcher_is_chosen_by_package_version(tmp_path: Path) -> None:
    """The newest cached launcher wins, not whichever cache hash sorts last.

    npm's ``_npx`` cache directories are named by an opaque hash, so
    ordering by path picks an arbitrary one. On this host the hash that
    sorted last held the *older* launcher (1.6.2 rather than 1.6.3), and
    the older launcher forwards the arguments it does not recognise straight
    to the transport binary -- which then refuses to boot on a flag it does
    not know.

    The directories below are laid out so that the path ordering and the
    version ordering disagree.
    """
    root = tmp_path / "_npx"
    newer = _cached_launcher(root, "aaa", "1.6.3")
    _cached_launcher(root, "zzz", "1.6.2")

    assert gateway.find_cached_bifrost_bin(root) == newer


def test_cached_launcher_falls_back_to_path_order_without_a_version(
    tmp_path: Path,
) -> None:
    """An unreadable ``package.json`` must not lose the candidate.

    The version is a preference, not a filter: a launcher whose metadata
    cannot be read is still usable, and losing it would push every launch
    through npx for no reason.
    """
    root = tmp_path / "_npx"
    launcher = root / "aaa" / "node_modules" / "@maximhq" / "bifrost" / "bin.js"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("// launcher", encoding="utf-8")

    assert gateway.find_cached_bifrost_bin(root) == launcher


def test_no_cached_launcher_returns_none(tmp_path: Path) -> None:
    """An empty cache is not an error."""
    root = tmp_path / "_npx"
    root.mkdir()
    assert gateway.find_cached_bifrost_bin(root) is None
