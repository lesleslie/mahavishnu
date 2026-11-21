"""A CLI command must work when it is invoked from inside a running loop.

``asyncio.run`` refuses to start a new event loop when one is already
running in this thread, and raises ``RuntimeError: asyncio.run() cannot
be called from a running event loop``. Every CLI command that drives an
async helper called ``asyncio.run`` directly, so a command invoked from
async code -- an async test, or any in-process async caller -- died with
that RuntimeError instead of doing its work. The crash named neither the
cause nor the remedy: the command exited 1 with a stack trace pointing at
the event loop rather than at the command.

``mahavishnu.core.async_patterns.run_sync`` drives the coroutine on its
own loop in a worker thread when a loop is already running, and on
``asyncio.run`` otherwise.

Reproduced before the fix with six lines::

    asyncio.run(CliRunner().invoke(app, ["pool", "health"]))

which raised ``RuntimeError('asyncio.run() cannot be called from a
running event loop')`` and left the coroutine un-awaited.
"""

from __future__ import annotations

import asyncio
import contextvars
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu._main_cli import app
from mahavishnu.backup_cli import add_backup_commands
from mahavishnu.core.async_patterns import run_sync

runner = CliRunner()


def test_run_sync_outside_a_running_loop() -> None:
    """The ordinary path: no loop is running, so asyncio.run drives it."""

    async def _work() -> str:
        await asyncio.sleep(0)
        return "done"

    assert run_sync(_work()) == "done"


async def test_run_sync_inside_a_running_loop() -> None:
    """The path that used to crash: this test's own loop is running.

    ``asyncio.run`` raises here -- it cannot start a second event loop in
    a thread that already has one -- so the helper has to take the
    worker-thread path instead.
    """

    async def _work() -> str:
        await asyncio.sleep(0)
        return "done"

    assert run_sync(_work()) == "done"


async def test_run_sync_cancels_pending_tasks_like_asyncio_run() -> None:
    """The worker path tears down like ``asyncio.run`` does.

    ``asyncio.run`` cancels the tasks still pending when the coroutine
    returns. The hand-rolled path only closed the loop, so a task left
    running outlived the command.
    """
    cancelled: list[str] = []

    async def _background() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append("cancelled")
            raise

    async def _work() -> None:
        asyncio.create_task(_background())
        await asyncio.sleep(0)  # let the task start

    run_sync(_work())

    assert cancelled == ["cancelled"]


async def test_run_sync_shuts_down_async_generators_like_asyncio_run() -> None:
    """A suspended async generator is closed when the command returns.

    The other half of ``asyncio.run``'s teardown: an async generator
    left suspended is shut down, so it does not outlive the command.
    """
    closed: list[str] = []

    async def _generator():
        try:
            yield None
            await asyncio.sleep(30)
        finally:
            closed.append("closed")

    async def _work() -> None:
        agen = _generator()
        await agen.asend(None)  # start it, leave it suspended

    run_sync(_work())

    assert closed == ["closed"]


async def test_run_sync_propagates_the_coroutines_exception() -> None:
    """The helper does not swallow what the coroutine raised."""

    async def _boom() -> None:
        msg = "boom"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="boom"):
        run_sync(_boom())


async def test_run_sync_propagates_an_interrupt() -> None:
    """An interrupt reaches the caller, and the worker is not waited on.

    The worker runs the coroutine on its own loop, so an interrupt has
    to travel back out of the thread -- and the caller's thread must
    not hang waiting for a worker that is already stopping.
    """

    async def _boom() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_sync(_boom())


async def test_run_sync_carries_the_callers_context() -> None:
    """The worker thread starts with an empty context; the caller's is carried.

    ``contextvars`` are per-thread, and a worker thread starts with an
    empty context. The logging context oneiric binds to a request id
    lives there, so a command driven from async code would otherwise log
    without the context its caller had.
    """
    var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id")
    var.set("trace-42")

    async def _work() -> str:
        return var.get()

    assert run_sync(_work()) == "trace-42"


async def test_cli_command_runs_from_inside_a_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CLI command that drives an async helper works in async context.

    ``mahavishnu pool health`` is the command the RuntimeError was
    reported against; ``pool list`` is the cheap sibling that drives the
    same helper, and it asserts the command's own outcome rather than
    only the absence of the crash.

    The app is faked, the way the sibling pool-list tests fake it: the
    real one has a pool manager only when pools are enabled, and this
    test's outcome must not depend on the machine's settings.
    """
    fake_app = SimpleNamespace(
        pool_manager=SimpleNamespace(list_pools=AsyncMock(return_value=[]))
    )
    monkeypatch.setattr("mahavishnu._main_cli.MahavishnuApp", lambda *a, **k: fake_app)

    result = runner.invoke(app, ["pool", "list"])

    assert not isinstance(result.exception, RuntimeError), (
        f"the CLI raised the running-loop RuntimeError: {result.exception!r}"
    )
    assert result.exit_code == 0, result.output


async def test_a_second_cli_module_runs_from_inside_a_running_loop() -> None:
    """The sweep covers every CLI module, not just the root one.

    Every CLI module drives its async helpers the same way, so every
    one of them has the same crash. ``backup list`` is the cheap
    sibling: it reads the backup directory and prints.
    """
    backup_app = typer.Typer()
    add_backup_commands(backup_app)

    result = runner.invoke(backup_app, ["backup", "list"])

    assert not isinstance(result.exception, RuntimeError), (
        f"the CLI raised the running-loop RuntimeError: {result.exception!r}"
    )


async def test_an_unmounted_cli_sub_app_runs_from_inside_a_running_loop() -> None:
    """A CLI module the root app never mounts has the same crash.

    ``mahavishnu/workflows/cli_watch.py`` builds its own Typer sub-app
    and nothing registers it -- so it is reachable only by importing it
    and invoking the app directly, which is exactly what a test does.
    The sweep missed it because its filename is neither ``cli.py`` nor
    ``*_cli.py`` and its directory is ``workflows``.
    """
    from mahavishnu.workflows.cli_watch import watch_app

    result = runner.invoke(watch_app, ["emit", "wf-async", "--step", "s"])

    assert not isinstance(result.exception, RuntimeError), (
        f"the CLI raised the running-loop RuntimeError: {result.exception!r}"
    )


def test_no_cli_module_reaches_for_asyncio_run_itself() -> None:
    """The sweep stays done.

    ``asyncio.run`` cannot start a loop in a thread that already has
    one, so a CLI command driven from async code dies with a
    RuntimeError that names neither the cause nor the remedy. The
    shared helper is the only way in, and this fails the moment a new
    call site reaches for the event loop directly.
    """
    import mahavishnu

    package_root = Path(mahavishnu.__file__).parent
    offenders = [
        str(path.relative_to(package_root))
        for path in sorted(package_root.rglob("*.py"))
        if "asyncio.run(" in path.read_text()
        and _is_a_user_facing_sync_surface(
            path.relative_to(package_root), path.read_text()
        )
    ]

    assert offenders == [], (
        "these user-facing surfaces call asyncio.run directly: " + ", ".join(offenders)
    )


def _is_a_user_facing_sync_surface(relative: Path, source: str) -> bool:
    """Whether a package-relative path is a user-facing sync surface.

    Three ways to tell, because each naming convention alone misses
    something:

    - ``mahavishnu/workflows/cli_watch.py`` builds a Typer sub-app --
      its own docstring calls it "CLI watch command" -- but its filename
      is neither ``cli.py`` nor ``*_cli.py``, and its directory is
      ``workflows``, so every name-based rule skips it. The
      *behavioural* rule catches it: a module that builds a Typer app
      IS a CLI module, whatever it is called and wherever it lives.
    - ``mahavishnu/shell/`` is the interactive admin shell. It is not a
      CLI module by any naming rule, but its convenience functions and
      its ``%workflow`` magic are driven by a human, synchronously,
      and they are just as able to be called from inside a running
      loop.
    - The name-based rules are kept as well, because a CLI module can
      be a plain function module that never builds an app of its own.
    """
    parts = relative.parts
    if "typer.Typer(" in source:
        return True
    if parts and parts[0] == "shell":
        return True
    return (
        relative.name == "cli.py"
        or relative.name.endswith("_cli.py")
        or relative.name.startswith("cli_")
        or "cli" in parts[:-1]
    )


# ---------------------------------------------------------------------------
# The real Ctrl+C path
# ---------------------------------------------------------------------------
#
# ``asyncio.run`` (and ``asyncio.Runner``, which it uses) replaces the
# SIGINT handler with one that CANCELS the main task. A task blocked in a
# synchronous call cannot be cancelled -- the cancellation is only delivered
# when the task yields to the loop -- and ``run_sync``'s wait is exactly
# such a call. So under an ``asyncio.run`` caller, Ctrl+C used to do
# nothing at all: the command ran on and on, and the operator had no way
# to stop it.
#
# The real-signal test runs in a SUBPROCESS. A signal delivered to the
# pytest process would end the test run if the handler were wrong, and a
# subprocess makes the failure a readable assertion instead.

_SIGINT_PROBE = """
import asyncio
import os
import signal
import sys
import threading

sys.path.insert(0, {repo!r})

from mahavishnu.core.async_patterns import run_sync

stopped = []


async def _forever():
    try:
        while True:
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        stopped.append(1)
        raise


async def _driver():
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
    try:
        run_sync(_forever())
    except KeyboardInterrupt:
        print("INTERRUPTED")
        return
    print("NOT_INTERRUPTED")


asyncio.run(_driver())
print("STOPPED" if stopped else "NOT_STOPPED")
"""


def test_ctrl_c_stops_a_command_run_from_inside_asyncio_run() -> None:
    """Ctrl+C reaches the caller, and the coroutine on the worker stops.

    This is the ``mahavishnu acp serve`` shape: a command that runs
    until the operator stops it. The operator's Ctrl+C has to end the
    command, and it has to end it in the caller's thread -- the
    coroutine is on the worker's loop, so the worker is what has to be
    stopped.

    The subprocess must also EXIT. A worker thread left running would
    be joined by ``concurrent.futures`` at interpreter shutdown, and the
    process would hang instead of exiting.
    """
    repo = str(Path(__file__).resolve().parents[2])
    script = textwrap.dedent(_SIGINT_PROBE).format(repo=repo)

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, (
        f"the probe exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "INTERRUPTED" in result.stdout, (
        f"Ctrl+C did not reach the caller\nstdout:\n{result.stdout}"
    )
    assert "STOPPED" in result.stdout, (
        f"the coroutine kept running on the worker\nstdout:\n{result.stdout}"
    )


def test_run_sync_restores_the_default_sigint_handler_while_it_waits() -> None:
    """The handler is swapped for the wait, and put back afterwards.

    The mechanism behind the test above, checked without sending a
    signal: while ``run_sync`` waits, the caller's SIGINT handler is
    the default one, so an interrupt raises ``KeyboardInterrupt`` in the
    caller's thread instead of cancelling a task that cannot be
    cancelled. Afterwards the caller's own handler is back.
    """
    observed: dict[str, object] = {}

    async def _slow() -> None:
        await asyncio.sleep(0.4)

    async def _driver() -> None:
        def _sample() -> None:
            time.sleep(0.1)
            observed["during"] = signal.getsignal(signal.SIGINT)

        sampler = threading.Thread(target=_sample)
        before = signal.getsignal(signal.SIGINT)
        sampler.start()
        try:
            run_sync(_slow())
        finally:
            sampler.join()
        observed["before"] = before
        observed["after"] = signal.getsignal(signal.SIGINT)

    asyncio.run(_driver())

    assert observed["before"] is not signal.default_int_handler, (
        "asyncio.run did not replace the SIGINT handler, so this test "
        "is not exercising the case it claims to"
    )
    assert observed["during"] is signal.default_int_handler, (
        "the default SIGINT handler was not restored for the wait"
    )
    assert observed["after"] == observed["before"], (
        "the caller's own SIGINT handler was not put back"
    )
