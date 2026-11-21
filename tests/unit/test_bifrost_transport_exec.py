"""Tests for the supervisor's handling of a denied exec of the transport binary.

req: REQ-BIFROST-049

On 2026-11-20 the transport pin moved to v2.6.0 and the gateway did not come
up. The launcher downloaded the binary successfully ("Downloaded binary to
.../v2.6.0/bin/bifrost-http-0"), chmodded it, and then failed to exec it with
``spawnSync .../bifrost-http-0 EACCES`` -- five times in a row, 30 seconds
apart, because launchd's ``ThrottleInterval`` was the only thing retrying.

Two properties were missing, and both are pinned here:

1. the supervisor re-launches a launcher that dies *immediately*, on its own
   cadence, instead of leaving the retry to launchd; and
2. a cached transport binary that lost its execute bit is repaired before the
   launcher is spawned, because the launcher's own chmod runs only on the
   download path.

The distinction that matters in (1) is *died* versus *timed out*. A slow boot
must not be retried -- the existing readiness budget owns that case, and a
retry there would mask a real cold start.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from mahavishnu.bifrost import gateway

if TYPE_CHECKING:
    from pathlib import Path


class _FakeProc:
    """Minimal stand-in for the transport child process."""

    def __init__(self, returncode: int | None = None) -> None:
        self.returncode: int | None = returncode

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, _timeout: float | None = None) -> int:
        return self.returncode or 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = 0


@pytest.fixture
def _quiet_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``serve`` off the operator's real gateway."""

    async def fake_resolve() -> None:
        return None

    def fake_secrets() -> dict[str, str]:
        return {}

    def fake_cleanup(_proc: object) -> None:
        return None

    monkeypatch.setattr(gateway, "resolve_secrets", fake_resolve)
    monkeypatch.setattr(gateway, "load_secrets_env", fake_secrets)
    monkeypatch.setattr(gateway, "cleanup", fake_cleanup)
    monkeypatch.setattr(gateway, "LAUNCH_RETRY_BACKOFF_SECONDS", 0.0)


# ---------------------------------------------------------------------------
# the execute bit
# ---------------------------------------------------------------------------


def test_a_cached_binary_without_the_execute_bit_is_repaired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The launcher chmods only on the download path, so we repair it here.

    A binary that landed without its execute bit is exec'd exactly as it was
    found, on every boot, and fails with EACCES. Because the download is what
    would have fixed it, nothing upstream repairs it.
    """
    binary = tmp_path / "bifrost-http-0"
    binary.write_bytes(b"not really a binary")
    binary.chmod(0o644)

    monkeypatch.setattr(gateway, "transport_cache_dir", lambda: tmp_path)

    repaired = gateway.ensure_transport_executable()

    assert repaired == [binary]
    assert os.access(binary, os.X_OK)


def test_an_executable_cached_binary_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The repair is for the broken case only; a good file is untouched."""
    binary = tmp_path / "bifrost-http-0"
    binary.write_bytes(b"not really a binary")
    binary.chmod(0o755)
    before = binary.stat().st_mtime_ns

    monkeypatch.setattr(gateway, "transport_cache_dir", lambda: tmp_path)

    assert gateway.ensure_transport_executable() == []
    assert binary.stat().st_mtime_ns == before


def test_repairing_is_a_no_op_when_nothing_is_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty cache is not an error -- it just means the first boot downloads."""
    monkeypatch.setattr(gateway, "transport_cache_dir", lambda: tmp_path)

    assert gateway.ensure_transport_executable() == []


def test_the_cache_dir_follows_the_launcher_per_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The cache path mirrors the launcher's own ``cacheDir()``.

    If this drifts from the launcher's, the repair targets a directory the
    launcher never writes and the fix silently does nothing.
    """
    monkeypatch.setattr(gateway, "TRANSPORT_VERSION", "v9.9.9")
    monkeypatch.setattr(os, "environ", {"XDG_CACHE_HOME": str(tmp_path)})
    monkeypatch.setattr(gateway.sys, "platform", "linux")

    assert gateway.transport_cache_dir() == tmp_path / "bifrost" / "v9.9.9" / "bin"


# ---------------------------------------------------------------------------
# the re-launch
# ---------------------------------------------------------------------------


def test_a_launcher_that_dies_immediately_is_relaunched(
    monkeypatch: pytest.MonkeyPatch, _quiet_gateway: None
) -> None:
    """The denied exec is transient, so the supervisor retries it itself.

    Waiting for launchd's 30-second ``ThrottleInterval`` between attempts is
    what turned a two-second problem into a two-minute outage.
    """
    attempts: list[int] = []

    def fake_launch() -> _FakeProc:
        attempts.append(len(attempts) + 1)
        # The first two attempts die the way a denied exec does; the third
        # succeeds and stays alive.
        return _FakeProc(returncode=1) if len(attempts) < 3 else _FakeProc()

    def fake_wait(_proc: object, timeout: int = 0) -> bool:
        return len(attempts) >= 3

    monkeypatch.setattr(gateway, "launch_bifrost", fake_launch)
    monkeypatch.setattr(gateway, "wait_for_ready", fake_wait)

    assert gateway.serve() == 0
    assert len(attempts) == 3


def test_a_slow_boot_is_not_relaunched(
    monkeypatch: pytest.MonkeyPatch, _quiet_gateway: None
) -> None:
    """A launcher that did not die is a cold start, not a failed exec.

    The existing readiness budget owns the cold start. Retrying it would
    mask a real regression and burn the budget twice.
    """
    attempts: list[int] = []

    def fake_launch() -> _FakeProc:
        attempts.append(1)
        return _FakeProc()  # still running: poll() is None

    def fake_wait(_proc: object, timeout: int = 0) -> bool:
        return False

    monkeypatch.setattr(gateway, "launch_bifrost", fake_launch)
    monkeypatch.setattr(gateway, "wait_for_ready", fake_wait)

    gateway.serve()

    assert len(attempts) == 1


def test_the_supervisor_gives_up_after_the_configured_attempts(
    monkeypatch: pytest.MonkeyPatch, _quiet_gateway: None
) -> None:
    """A permanently broken launcher is reported, not retried forever."""
    attempts: list[int] = []

    def fake_launch() -> _FakeProc:
        attempts.append(1)
        return _FakeProc(returncode=1)

    def fake_wait(_proc: object, timeout: int = 0) -> bool:
        return False

    monkeypatch.setattr(gateway, "launch_bifrost", fake_launch)
    monkeypatch.setattr(gateway, "wait_for_ready", fake_wait)
    monkeypatch.setattr(gateway, "LAUNCH_ATTEMPTS", 3)

    assert gateway.serve() != 0
    assert len(attempts) == 3


def test_the_relaunch_is_reported_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _quiet_gateway: None,
) -> None:
    """A retry that is invisible reads as a hang.

    The CLI's own wait is 660 seconds long and reports progress on its own
    cadence; the supervisor's retry has to be visible too, or the operator
    sees nothing for the whole window.
    """
    attempts: list[int] = []

    def fake_launch() -> _FakeProc:
        attempts.append(1)
        return _FakeProc(returncode=1) if len(attempts) < 2 else _FakeProc()

    def fake_wait(_proc: object, timeout: int = 0) -> bool:
        return len(attempts) >= 2

    monkeypatch.setattr(gateway, "launch_bifrost", fake_launch)
    monkeypatch.setattr(gateway, "wait_for_ready", fake_wait)

    gateway.serve()

    assert "exited immediately" in capsys.readouterr().err


def test_the_transport_binary_is_repaired_before_the_launcher_is_spawned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The repair has to happen before the spawn, or it is a race.

    The launcher execs the transport binary as its own first action, so a
    repair that lands after the spawn cannot help the attempt that failed.
    """
    order: list[str] = []

    binary = tmp_path / "bifrost-http-0"
    binary.write_bytes(b"not really a binary")
    binary.chmod(0o644)

    monkeypatch.setattr(gateway, "transport_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(gateway, "find_cached_bifrost_bin", lambda: None)
    monkeypatch.setattr(gateway, "wrap_with_line_buffering", lambda cmd: cmd)

    def fake_popen(cmd: list[str], **kwargs: object) -> _FakeProc:
        order.append("spawn")
        assert os.access(binary, os.X_OK), "the binary was still not executable"
        return _FakeProc()

    monkeypatch.setattr(gateway.subprocess, "Popen", fake_popen)

    gateway.launch_bifrost()

    assert order == ["spawn"]
