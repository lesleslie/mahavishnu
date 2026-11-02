"""End-to-end verification that the Bifrost cache eviction sweep terminates.

req: REQ-BIFROST-042, REQ-BIFROST-043

Why this file exists
--------------------
The sweep shipped and then hung. ``coredis`` keeps a reader and a writer
task per connection inside an **anyio** task group, and the sweep drove it
with ``asyncio.run``. Under a plain asyncio runner the anyio task group is
never cancelled on the way out, so the process finished the sweep and then
blocked forever waiting on a socket read.

The failure was silent in the worst way:

* the launchd agent's exit status stayed ``-15`` and the job never went
  idle, so ``launchctl list`` showed a live PID forever;
* stdout was redirected to a file, so Python's block buffering meant the
  summary line never reached the log -- the log stayed *empty*, which
  looked like the sweep never ran at all;
* every foreground invocation looked fine, because the operator's shell
  saw the output before the process wedged.

So the assertions here are about **termination**, not about output. A
sweep that prints the right numbers and never exits is a failure.

The test drives the real CLI as a subprocess -- the same shape the
launchd timer uses -- and asserts it returns on its own.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_network]

#: How long the CLI may take. The sweep itself is a couple of seconds;
#: the rest is interpreter and import startup, which is slower cold.
#: A hang shows up as the timeout firing, which is the point.
TERMINATION_TIMEOUT = 180


def _cli() -> Path:
    """Locate the ``mahavishnu`` console script in the active venv."""
    candidate = Path(sys.executable).with_name("mahavishnu")
    if candidate.exists():
        return candidate
    pytest.skip(f"mahavishnu CLI not found next to {sys.executable}")


def test_cache_sweep_command_terminates() -> None:
    """``mahavishnu bifrost cache-sweep --dry-run`` must exit on its own.

    Uses ``--dry-run`` so the test observes the command without changing
    the store. The exit code and the summary are the assertions; a
    process that has to be killed fails them.
    """
    cli = _cli()
    try:
        completed = subprocess.run(
            [str(cli), "bifrost", "cache-sweep", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=TERMINATION_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"mahavishnu bifrost cache-sweep did not exit within "
            f"{TERMINATION_TIMEOUT}s -- the sweep is hanging on shutdown. "
            "coredis owns its connection tasks in an anyio task group and "
            "must be driven by anyio.run(), not asyncio.run()."
        )

    assert completed.returncode == 0, (
        f"cache-sweep exited {completed.returncode}\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
    assert "scanned=" in completed.stdout, (
        f"cache-sweep printed no summary line\nstdout: {completed.stdout}"
    )
    assert "expired=" in completed.stdout, (
        f"cache-sweep summary is missing the expired count\nstdout: {completed.stdout}"
    )


def test_cache_sweep_dry_run_deletes_nothing() -> None:
    """A dry run must not remove anything.

    The store is shared with the event bus, so a dry run that deleted
    entries would be a destructive operation behind a read-only flag.
    """
    redis = pytest.importorskip("redis", reason="redis client not installed")
    import time

    client = redis.Redis(host="localhost", port=6379, decode_responses=False)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis is not reachable at localhost:6379")

    def _expired_count() -> int:
        now = time.time()
        count = 0
        for key in client.keys("Bifrost*"):
            raw = client.hget(key, b"expires_at")
            if raw is None:
                continue
            try:
                if float(raw) <= now:
                    count += 1
            except (TypeError, ValueError):
                continue
        return count

    before = _expired_count()
    cli = _cli()
    completed = subprocess.run(
        [str(cli), "bifrost", "cache-sweep", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=TERMINATION_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    after = _expired_count()

    assert after == before, (
        f"a dry run changed the expired-entry count: {before} -> {after}"
    )


def test_sweep_leaves_non_bifrost_keys_alone() -> None:
    """The event bus and the Oneiric queue share this Redis.

    The sweep matches only the Bifrost cache prefixes. If it ever widened
    to a bare ``KEYS *``, it would start deleting event history.
    """
    redis = pytest.importorskip("redis", reason="redis client not installed")

    client = redis.Redis(host="localhost", port=6379, decode_responses=False)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis is not reachable at localhost:6379")

    before = {
        key
        for key in client.keys("*")
        if not key.startswith(b"Bifrost")
    }
    cli = _cli()
    completed = subprocess.run(
        [str(cli), "bifrost", "cache-sweep", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=TERMINATION_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    after = {
        key
        for key in client.keys("*")
        if not key.startswith(b"Bifrost")
    }

    removed = before - after
    assert not removed, (
        "the sweep removed non-Bifrost keys: "
        + ", ".join(sorted(key.decode("utf-8", "replace") for key in removed))
    )


@pytest.mark.skipif(
    not Path.home().joinpath("Library/LaunchAgents/ai.bifrost.cache-sweep.plist").exists(),
    reason="the cache-sweep launchd agent is not installed",
)
def test_launchd_agent_is_loaded() -> None:
    """The scheduled sweep must be registered with launchd.

    Without this, the store grows unbounded again -- the whole point of
    the timer.
    """
    result = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "ai.bifrost.cache-sweep" in result.stdout, (
        "ai.bifrost.cache-sweep is not loaded; the store will grow unbounded. "
        "Install it with:\n"
        "  cp config/launchd/ai.bifrost.cache-sweep.plist ~/Library/LaunchAgents/\n"
        "  launchctl bootstrap gui/$(id -u) "
        "~/Library/LaunchAgents/ai.bifrost.cache-sweep.plist"
    )


def test_launchd_agent_log_shows_a_completed_sweep() -> None:
    """The agent's log must carry a completed sweep.

    An empty log is the signature of the hang: the process did the work
    but never flushed stdout because it never exited.
    """
    log = Path.home() / ".local" / "state" / "mcp" / "logs" / "bifrost-cache-sweep.log"
    if not log.exists():
        pytest.skip(f"{log} does not exist; the agent has not run yet")
    content = log.read_text(encoding="utf-8", errors="replace")
    assert "cache_sweep_completed" in content, (
        f"{log} carries no completed sweep:\n{content[-2000:]}"
    )
