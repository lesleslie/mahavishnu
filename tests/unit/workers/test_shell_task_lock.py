"""Serialisation of the staged-command handoff -- CWE-362 regression.

Shepherd's ``TaskLibrary.register`` keys a task by its import path, so every
shell dispatch resolves to the *same* callable and the command cannot travel
in a closure -- it is staged in a module global in ``_shell_task``. That slot
is process-wide. Without serialisation around both the staging and the run,
two concurrent dispatches interleave: A stages its command, B overwrites it,
and A's run executes B's command.

These tests read the staged slot at the moment the substrate would execute
it, which is the only point where the cross-talk is observable.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from mahavishnu.workers import _shell_task
from mahavishnu.workers import shepherd_backend as _sb_module

#: The real staging path. Captured at import, before ``stub_shepherd``
#: replaces it with a double that skips ``set_command`` entirely -- that
#: double is fine for asserting call plumbing, but this module tests the
#: handoff through ``_shell_task``'s process-wide slot, which the double
#: bypasses and therefore would never populate.
_REAL_COMPOSE = _sb_module._compose_shell_task

# ``stub_shepherd`` is a module-local fixture (it patches ``shepherd``'s
# symbols on the backend module, which is why it cannot live in conftest).
# Importing it is the supported way to share a fixture across modules; the
# alternative is duplicating ~90 lines of substrate doubles.
from tests.unit.workers.test_shepherd_backend import (  # noqa: F401  # pytest fixture
    stub_shepherd,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.usefixtures("stub_shepherd")


def _worker_cls() -> Any:
    from mahavishnu.workers import shepherd_backend

    return shepherd_backend


async def _observe_staged_commands(worker: Any) -> list[str]:
    """Run two concurrent shell dispatches; return what each run saw.

    The observation point is inside ``Workspace.run`` -- after the command was
    staged, at the moment the substrate would execute the task.
    """
    sb = _worker_cls()
    original_run = sb.ShepherdWorkspace.run
    original_compose = sb._compose_shell_task
    observed: list[str] = []

    async def _run(self: Any, task_ref: Any, **kwargs: Any) -> Any:
        # Yield first. The stub's ``run`` is synchronous, so without an await
        # point here the two dispatches cannot interleave at all and the test
        # would pass whether or not the lock exists -- verified: it did.
        await asyncio.sleep(0)
        observed.append(_shell_task._PENDING_COMMAND["value"])
        result = original_run(self, task_ref, **kwargs)
        return result

    sb._compose_shell_task = _REAL_COMPOSE
    sb.ShepherdWorkspace.run = _run  # type: ignore[method-assign]
    try:
        await asyncio.gather(*(_dispatch(worker, cmd) for cmd in ("echo A", "echo B")))
    finally:
        sb.ShepherdWorkspace.run = original_run  # type: ignore[method-assign]
        sb._compose_shell_task = original_compose
    return observed


async def _dispatch(worker: Any, command: str) -> Any:
    return await worker.execute({"command": command})


async def test_concurrent_dispatches_do_not_cross_talk(tmp_path: Path) -> None:
    """Each concurrent dispatch must run the command it asked for.

    Without the lock the usual outcome is B's command staged for both runs
    and A's never observed -- a worker silently executing someone else's
    command, which is exactly the finding.
    """
    sb = _worker_cls()
    worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
    await worker.start()

    observed = await _observe_staged_commands(worker)

    # ``execute`` stages the *sanitized* command, which quoting-wraps it, so
    # compare against that rather than the raw input.
    from mahavishnu.workers import _exec_guard

    expected = {_exec_guard.sanitize_command(cmd) for cmd in ("echo A", "echo B")}
    assert set(observed) == expected, (
        f"the substrate saw {observed!r}; each dispatch must observe its own command"
    )


async def test_lock_is_released_after_the_run(tmp_path: Path) -> None:
    """A second dispatch must not be blocked by a settled first one.

    Guards against holding the lock past the run, which would serialise the
    pool to one worker at a time.
    """
    sb = _worker_cls()
    worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
    await worker.start()

    await asyncio.wait_for(worker.execute({"command": "echo first"}), timeout=10)
    await asyncio.wait_for(worker.execute({"command": "echo second"}), timeout=10)

    assert not sb._SHELL_COMMAND_LOCK.locked()


async def test_first_class_task_ref_needs_no_lock(tmp_path: Path) -> None:
    """``task_ref`` bodies carry their own closure and bypass the slot."""
    sb = _worker_cls()
    worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
    await worker.start()

    result = await worker.execute({"task_ref": sb.run_shell_command})

    assert result.metadata["command"] is None


async def test_staging_survives_a_failed_run(tmp_path: Path) -> None:
    """A run that raises must not leave the lock held forever."""
    sb = _worker_cls()
    worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
    await worker.start()

    original_run = sb.ShepherdWorkspace.run

    def _boom(self: Any, task_ref: Any, **kwargs: Any) -> Any:
        raise RuntimeError("substrate exploded")

    sb.ShepherdWorkspace.run = _boom  # type: ignore[method-assign]
    try:
        result = await worker.execute({"command": "echo A"})
    finally:
        sb.ShepherdWorkspace.run = original_run  # type: ignore[method-assign]

    assert result.status.value == "failed"
    assert not sb._SHELL_COMMAND_LOCK.locked(), "lock must be released on the failure path"
