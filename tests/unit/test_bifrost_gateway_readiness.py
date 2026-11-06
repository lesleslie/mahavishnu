"""Tests for the Bifrost gateway supervisor's readiness budget.

req: REQ-BIFROST-033 (lifecycle), extended by the 2026-11-06 cold-start fix.

The supervisor kills the transport binary if it has not bound the port
within ``gateway.READY_TIMEOUT_SECONDS``. Two properties have to hold, and
the first one is the one that regressed:

- the budget must clear the **worst cold start this fleet actually shows**,
  not merely relate to the CLI's own wait; and
- the clock must start *before* the spawn, because the spawn itself (fork
  plus a launcher that can stall on its own network fetch) can take minutes
  on a loaded host.

The earlier guard pinned only the relative relationship between the two
timeouts. That let both be shrunk together below the real cold start and
still pass -- which is exactly what happened. The 2026-10-29 fix raised the
budget from 60s to 210s, still well under the 329s this host needs.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from mahavishnu.bifrost import gateway, lifecycle

if TYPE_CHECKING:
    from pathlib import Path

#: Worst observed cold start on this fleet, from launchd spawn to the UI
#: accepting connections: 5m29s (329s), measured 2026-11-06 on a host whose
#: load average peaked at 131 while the rest of the MCP fleet was starting.
#: A warm boot is ~26s; the boot that matters is the one where the gateway
#: is launched *alongside* the fleet.
OBSERVED_COLD_START_SECONDS = 329


class _FakeProc:
    """Minimal stand-in for the transport child process."""

    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, _timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = 0


# ---------------------------------------------------------------------------
# the budget itself
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-BIFROST-045"])
def test_readiness_budget_clears_the_worst_observed_cold_start() -> None:
    """The budget must clear the worst measured cold start.

    The guard that missed this only asserted ``budget > timeout``. Both
    numbers could be tuned downward together and the assertion would still
    hold, so the budget stayed below the time the gateway actually needs --
    and the supervisor killed a healthy gateway mid-boot.
    """
    assert gateway.READY_TIMEOUT_SECONDS >= OBSERVED_COLD_START_SECONDS
    assert lifecycle.READY_BUDGET_SECONDS >= OBSERVED_COLD_START_SECONDS


@pytest.mark.req(["REQ-BIFROST-045"])
def test_readiness_budget_outlasts_the_bind_timeout() -> None:
    """The parent's wait must outlast the child's own bind timeout.

    The supervisor writes the ready file only *after* the child binds, so
    the CLI's budget has to exceed the supervisor's bind timeout or the
    gate can give up on a gateway that is about to come up.
    """
    assert lifecycle.READY_BUDGET_SECONDS > gateway.READY_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# where the clock starts
# ---------------------------------------------------------------------------


def test_bind_wait_is_the_remainder_of_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bind wait gets what is left of the budget, not a fresh full one.

    ``launch_bifrost`` forks a large interpreter and execs a launcher that
    can stall on its own network fetch. Anchoring the deadline after the
    spawn hands the child a second, full budget, so the supervisor's
    effective patience becomes unbounded -- a slow spawn could then keep
    the job alive indefinitely.
    """
    seen: dict[str, int] = {}

    def fake_launch() -> _FakeProc:
        # Simulate a spawn that consumed part of the budget.
        time.sleep(0.05)
        return _FakeProc()

    def fake_wait(_proc: object, timeout: int = 0) -> bool:
        seen["timeout"] = timeout
        return True

    async def fake_resolve() -> None:
        return None

    def fake_secrets() -> dict[str, str]:
        return {}

    def fake_cleanup(_proc: object) -> None:
        return None

    monkeypatch.setattr(gateway, "resolve_secrets", fake_resolve)
    monkeypatch.setattr(gateway, "load_secrets_env", fake_secrets)
    monkeypatch.setattr(gateway, "launch_bifrost", fake_launch)
    monkeypatch.setattr(gateway, "wait_for_ready", fake_wait)
    monkeypatch.setattr(gateway, "cleanup", fake_cleanup)

    gateway.serve()

    # The spawn ate 50ms, so the remaining budget is strictly less than the
    # full one. A deadline anchored *after* the spawn would hand back the
    # full budget instead.
    assert 0 < seen["timeout"] < gateway.READY_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# operator feedback during a long wait
# ---------------------------------------------------------------------------


def test_readiness_wait_reports_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A long, quiet wait reports progress instead of looking like a hang.

    The budget is deliberately generous, so ``bifrost start`` can block for
    minutes. Silence during that window reads as a hang rather than as a
    gateway that is still booting.
    """
    ready = tmp_path / "bifrost.ready"

    def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(lifecycle, "READY_FILE", ready)
    monkeypatch.setattr(lifecycle, "REPORT_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(lifecycle.time, "sleep", fake_sleep)

    assert lifecycle.wait_for_ready_file(timeout=1) is False

    assert "budget left" in capsys.readouterr().out


def test_readiness_wait_returns_as_soon_as_the_ready_file_appears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wait is a poll, not a sleep -- a present ready file returns at once."""
    ready = tmp_path / "bifrost.ready"
    ready.touch()
    monkeypatch.setattr(lifecycle, "READY_FILE", ready)

    assert lifecycle.wait_for_ready_file(timeout=60) is True
